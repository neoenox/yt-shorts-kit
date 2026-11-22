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


def project_root(script_file, levels=1):
    """プロジェクトのルート。環境変数 YT_PROJECT_ROOT が優先、無ければ script_file の levels 個上(既定は scripts/ の1つ上)。"""
    env = os.environ.get(ENV_ROOT)
    if env:
        return Path(env)
    return Path(script_file).resolve().parents[levels]


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
