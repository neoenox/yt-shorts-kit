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


VIDEO_QUESTION = (
    'この動画を最後まで通して見て、Short動画としてレビューしてください。'
    'まず、ナレーションを時刻つきで書き起こしてください。'
    '次に、次の項目をそれぞれ分けて報告してください。'
    '(1) 音声の読み間違い・音割れ・無音。'
    '(2) 字幕の表記そのものの違和感。人名のカタカナ／ひらがな、漢数字と算用数字、専門用語の表記、'
    '読み仮名をそのまま字幕に出していないかを、音声の読みとは別に評価してください。'
    '音声が正しく読めていても、字幕の文字が不自然なら必ず指摘してください。'
    '(3) 字幕と音声の一致と、タイミングのズレ。'
    '(4) 文字の重なり・はみ出し・見切れ・折り返し。'
    '(5) 事実関係と、根拠より強い断定。'
    '(6) 冒頭1〜3秒の引き。'
    '(7) AI映像の不自然さ（文字・人物・現代物の混入）。'
    '(8) 画面下端や右端のUI被り。実際に被っている場合だけ指摘し、'
    '推測になる場合は「要確認」と分けてください。'
    '指摘には時刻と、修正後の文字列の候補を具体的に書いてください。'
    '最後に「公開可」か「修正必要」かを明示してください。'
    '表は使わず、見出しと箇条書きだけで報告してください。'
)


def build_video_prompt(title=''):
    """完成動画を Google AI に送るときの依頼文。"""
    head = f'動画「{title}」をレビューしてください。\n' if title else ''
    return head + VIDEO_QUESTION


def build_prompt(script, target):
    """target は 'chatgpt' または 'google'。"""
    if target == 'chatgpt':
        return build_chatgpt_prompt(script)
    if target == 'google':
        return build_google_prompt(script)
    raise ValueError(f'未知の target: {target}')
