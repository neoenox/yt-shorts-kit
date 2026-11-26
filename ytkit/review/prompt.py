"""共通形から ChatGPT / Google AI への依頼文を組み立てる。"""

MARK = '===ここまでが台本です==='

RULES = [
    'あなたは、YouTube Shorts の台本の査読者です。以下の台本を、公開前の確認として評価してください。',
    '',
    '【守ってほしいこと】',
    '・台本を書き直さないでください。指摘と改善案の列挙だけにしてください。',
    '・新しい事実を挙げる場合は、必ず出典URLを付けてください。出典が無い場合は「確認できず」と書いてください。',
    '・断定できないことは「自信が低い」と明記してください。',
]

OUTPUT_RULES = [
    '【出力形式】',
    '1. 総評（「公開可」「修正必要」「作り直し」のいずれか）と理由を3行以内。',
    '2. 指摘の一覧（表は使わず、1件ずつ「重大度: 高/中/低」「箇所: シーン番号か文」「指摘: …」「根拠: …」の4行で箇条書き）',
    '3. 問題ないと判断した点',
    '4. 自信の低い判断',
    '',
    '（表は使わないでください。見出しと箇条書きだけで結構です。）',
]


def _scenes(script):
    lines = []
    for i, sc in enumerate(script.get('scenes', []), 1):
        lines.append(f"{i}. ナレーション: {sc.get('text', '')}")
        if sc.get('big'):
            lines.append(f"   大見出し: {sc['big']}")
        if sc.get('caption'):
            lines.append(f"   テロップ: {sc['caption']}")
        if sc.get('source'):
            lines.append(f"   画面 / 出典: {sc['source']}")
    return lines


def _claims(script):
    lines = []
    for c in script.get('claims', []):
        lines.append(
            f"[{c.get('id', '')}] {c.get('statement', '')}\n"
            f"    出典: {c.get('source_url', '')}\n"
            f"    確認メモ: {c.get('evidence_note', '')[:220]}"
        )
    return lines


def build_chatgpt_prompt(script):
    parts = list(RULES)
    parts += [
        '',
        '【動画の前提】',
        f"・プロジェクト: {script.get('project', '')} / 企画: {script.get('slug', '')}",
        f"・長さ {len(script.get('scenes', []))} 場面の Shorts（縦1080x1920）。",
        '',
        '【評価の観点】',
        'A. 事実の正確さ（数値・条件・帰属。資料の記載と食い違っていないか）',
        'B. 出典と主張の対応（その主張を、その出典で支えられるか。足りない根拠はどれか）',
        'C. 聞きやすさ（音声合成で読み間違えそうな語、同音異義、数字の読み、1文の長さ）',
        'D. 構成と引き（最初の3秒で引きつけるか、結論の回収、テンポ）',
        'E. 抜けている文脈・誤解を招く表現（前提の欠落、断定しすぎ、比較の不公平）',
        '',
    ]
    parts += OUTPUT_RULES
    parts += [
        '',
        f"【動画の題材】{script.get('title', '')}",
        f"【フック】{script.get('hook', '')}",
        '',
        '【台本】',
    ]
    parts += _scenes(script)
    parts += ['', '【主張と出典】']
    parts += _claims(script)
    if script.get('needs_research'):
        parts += ['', '【未確認】' + ' / '.join(script['needs_research'])]
    parts += ['', MARK]
    return '\n'.join(parts)


def build_google_prompt(script):
    parts = list(RULES)
    parts += [
        '',
        f"Short動画「{script.get('title', script.get('slug', ''))}」の台本を査読してください。",
        '見てほしい点: 事実の誤り、根拠より強い断定、誤解を招く表現、'
        '音声で聞きにくい語、画面に出る文字の表記（人名のカタカナ／ひらがな、'
        '漢数字と算用数字、読み仮名の直出し）、字幕と音声の一致、'
        '文字の重なり・見切れ、公開可か修正必要か。',
        'AIの指摘は根拠の原文と照合してから採用します。',
        '',
    ]
    parts += OUTPUT_RULES
    parts += ['', '【台本】']
    parts += _scenes(script)
    parts += ['', '【主張と出典】']
    parts += _claims(script)
    if script.get('needs_research'):
        parts += ['', '【未確認】' + ' / '.join(script['needs_research'])]
    parts += ['', MARK]
    return '\n'.join(parts)


def build_prompt(script, target):
    """target は 'chatgpt' または 'google'。"""
    if target == 'chatgpt':
        return build_chatgpt_prompt(script)
    if target == 'google':
        return build_google_prompt(script)
    raise ValueError(f'未知の target: {target}')
