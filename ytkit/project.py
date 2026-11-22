"""プロジェクト(チャンネル)ごとの設定を読む。

コア部品が「どのプロジェクトで動いているか」を知る入口:
  project_root(__file__)  … プロジェクトの場所。環境変数 YT_PROJECT_ROOT があればそれ、無ければスクリプトの1つ上
  load_config(root)       … root/channel.toml を読む(同じファイルは1回だけ読む)
  require(cfg, 'a.b')     … 'a.b' を取り出す。無ければ、どのキーが足りないかを名指しして止める

チャンネル固有の値(名前・ナレーター・BGM・フォント)は、コードではなく各プロジェクトの channel.toml に置く。
"""
import functools
import os
import tomllib
from pathlib import Path

CONFIG_NAME = 'channel.toml'
ENV_ROOT = 'YT_PROJECT_ROOT'


class ConfigError(RuntimeError):
    pass


def _find_up(start):
    """start から親へたどって、channel.toml があるフォルダーを探す。無ければ None。"""
    start = Path(start).resolve()
    for d in (start, *start.parents):
        if (d / CONFIG_NAME).exists():
            return d
    return None


def project_root(script_file, levels=1):
    """プロジェクトのルート。順序: 環境変数 YT_PROJECT_ROOT → script_file の levels 個上に channel.toml があればそこ →
    カレントから親へたどって channel.toml を探す → script_file の levels 個上(従来の既定。scripts/ の1つ上)。
    共有パッケージ(ytcore)の中から呼ぶと script_file はプロジェクトの外なので、プロジェクト側の入口が YT_PROJECT_ROOT を設定する。"""
    env = os.environ.get(ENV_ROOT)
    if env:
        return Path(env)
    near = Path(script_file).resolve().parents[levels]
    if (near / CONFIG_NAME).exists():
        return near
    return _find_up(Path.cwd()) or near


@functools.lru_cache(maxsize=None)
def _load(path):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def load_config(root, name=CONFIG_NAME):
    """root/channel.toml を dict で返す。同じファイルは1回だけ読む(呼び出し側が dict を書き換えると共有される点に注意)。"""
    p = Path(root) / name
    if not p.exists():
        raise ConfigError(f'設定ファイルが無い: {p}（プロジェクトのルートに {name} を置く。環境変数 {ENV_ROOT} で場所を変えられる）')
    return _load(str(p))


def section(cfg, name, keys):
    """設定の1節から、必要なキーだけを dict で取り出す。足りないキーは ConfigError(キー名つき)。
    呼び出し側は実行時にこの dict を引くので、書き換えると反映される(テストで差し替えやすい)。"""
    return {k: require(cfg, f'{name}.{k}') for k in keys}


def require(cfg, dotted):
    """'channel.name' のような経路で値を取り出す。無ければ ConfigError(足りないキー名つき)。"""
    cur = cfg
    for k in dotted.split('.'):
        if not isinstance(cur, dict) or k not in cur:
            raise ConfigError(f'設定にキーが無い: {dotted}（{CONFIG_NAME} の [{dotted.rsplit(".", 1)[0]}] に {k} を足す）')
        cur = cur[k]
    return cur
