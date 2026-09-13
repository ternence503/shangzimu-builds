"""Local, lossless subtitle wrapping and conservative word-timed splitting."""
import math
import re
import unicodedata

# Conservative local phrase hints, not a cloud model or a complete Chinese parser.
COMMON_TERMS = ('這裡', '那裡', '哪裡', '為什麼', '什麼', '我們', '你們', '他們',
                '今天', '事情', '重要', '特別', '因為', '所以', '但是', '不過',
                '然後', '而且', '就是', '來到', '一起', '專輯', '封面', '講座',
                '字幕', '產品', '設計', '需要', '可以', '已經', '如果', '例如',
                '接著', '首先', '最後', '另外', '同時', '這個', '那個', '有件')
CONNECTIVES = ('因為', '所以', '但是', '不過', '然後', '而且', '接著', '另外')


def _canonical(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _tokens(text, terms):
    # Existing line breaks are layout instructions, not subtitle content.
    text = text.replace('\r', '').replace('\n', '')
    protected = sorted(set(t for t in (*terms, *COMMON_TERMS) if isinstance(t, str) and t), key=len, reverse=True)
    # Latin words and numeric units stay intact; Chinese prose otherwise wraps by character.
    patterns = [re.escape(t) for t in protected]
    patterns += [r'第[一二三四五六七八九十百千零〇兩\d]+(?:張|次|個|位|屆|集|章|節|頁|名|天|年|部|首|段)',
                 r'[A-Za-z]+(?:[\-\'’][A-Za-z]+)*',
                 r'\d+(?:[.,:]\d+)*(?:\s?(?:公里|公尺|公斤|毫秒|分鐘|小時|秒|分|年|月|日|元|萬|億|%|％|kg|km|ms|cm|mm|GB|MB|px))?']
    pattern = re.compile('|'.join(patterns))
    result = []
    offset = 0
    while offset < len(text):
        match = pattern.match(text, offset)
        token = match.group() if match else text[offset]
        result.append(token)
        offset += len(token)
    # Keep punctuation attached to the preceding token, preventing punctuation-only lines.
    joined = []
    for token in result:
        if joined and all(unicodedata.category(c).startswith('P') for c in token):
            joined[-1] += token
        else:
            joined.append(token)
    return joined


def _break_score(tokens, index):
    if index <= 0 or index >= len(tokens):
        return 0
    left = ''.join(tokens[max(0, index - 6):index]).rstrip()
    right = ''.join(tokens[index:index + 8]).lstrip()
    if left[-1:] in '。！？；.!?;':
        return 10
    if left[-1:] in '，：、,:':
        return 7
    if any(right.startswith(word) for word in CONNECTIVES):
        return 6
    if left.endswith(('就是', '的是')) and right.startswith(('我們', '你們', '要', '需要', '因為')):
        return 6
    return 1 if tokens[index - 1].isspace() or tokens[index].isspace() else 0


def _lines(tokens, limit):
    # Minimise number of lines first, then favour clause boundaries and balanced
    # lengths. Avoid greedy filling that leaves a two-character orphan line.
    count = len(tokens)
    costs = [float('inf')] * (count + 1)
    stops = [count] * (count + 1)
    costs[count] = 0
    for begin in range(count - 1, -1, -1):
        size = 0
        for stop in range(begin + 1, count + 1):
            size += len(tokens[stop - 1])
            if size > limit and stop > begin + 1:
                break
            line = ''.join(tokens[begin:stop])
            if not line.strip():
                continue
            useful = len(line.strip())
            short = max(0, min(4, limit * .3) - useful) * 5
            cost = 100 + costs[stop] + ((limit - min(useful, limit)) / limit) ** 2 * 4 + short
            if stop < count:
                cost -= _break_score(tokens, stop) * 3
            if cost < costs[begin]:
                costs[begin], stops[begin] = cost, stop
    lines = []
    index = 0
    while index < len(tokens):
        stop = stops[index]
        lines.append((index, stop, ''.join(tokens[index:stop])))
        index = stop
    # Preserve spaces without generating whitespace-only SRT lines.
    cleaned = []
    pending = ''
    pending_start = 0
    for begin, stop, text in lines:
        if not text.strip():
            if cleaned:
                old_begin, _, old_text = cleaned[-1]
                cleaned[-1] = (old_begin, stop, old_text + text)
            else:
                pending += text
                pending_start = begin
        else:
            cleaned.append((pending_start if pending else begin, stop, pending + text))
            pending = ''
    lines = cleaned
    return lines


def _timing_boundaries(segment, tokens):
    words = segment.get('words')
    if not isinstance(words, list) or not words:
        return None
    offsets = {}
    canonical = ''
    previous = segment['start']
    for word in words:
        if not isinstance(word, dict):
            return None
        text = word.get('word', word.get('text'))
        start, end = word.get('start'), word.get('end')
        if not isinstance(text, str) or not _number(start) or not _number(end):
            return None
        if start < previous or end <= start or end > segment['end']:
            return None
        piece = _canonical(text)
        if not piece:
            return None
        canonical += piece
        offsets[len(canonical)] = (end, start)
        previous = end
    if canonical != _canonical(segment['text']):
        return None
    result = {}
    consumed = 0
    for index, token in enumerate(tokens, 1):
        consumed += len(_canonical(token))
        if consumed in offsets:
            result[index] = offsets[consumed][0]
    return result


def layout_subtitles(segments, max_chars=18, max_lines=2, protected_terms=(), split_clauses=True):
    """Return fresh cue dictionaries and cue-numbered warnings, without mutating input.

    Width counts Python characters (not rendered pixels). Splits require exact word
    alignment after ignoring punctuation and whitespace; no estimated timestamps.
    """
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError('每行字數必須是大於零的整數。')
    if isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines < 1:
        raise ValueError('每塊行數必須是大於零的整數。')
    if protected_terms is None or isinstance(protected_terms, str):
        raise ValueError('保護詞組必須是文字清單。')
    terms = tuple(protected_terms)
    output, warnings = [], []
    for number, segment in enumerate(segments, 1):
        if not isinstance(segment, dict) or not isinstance(segment.get('text'), str):
            raise ValueError('原稿第 %d 塊字幕內容格式無效。' % number)
        if not segment['text'].strip():
            raise ValueError('原稿第 %d 塊字幕沒有文字。' % number)
        start, end = segment.get('start'), segment.get('end')
        if not _number(start) or not _number(end) or start < 0 or end <= start:
            raise ValueError('原稿第 %d 塊字幕起迄時間無效。' % number)
        word_terms = ()
        if _timing_boundaries(segment, list(segment['text'])):
            word_terms = tuple(_canonical(word.get('word', word.get('text')))
                               for word in segment['words']
                               if 2 <= len(_canonical(word.get('word', word.get('text')))) <= 8
                               and re.search(r'[\u3400-\u9fff]', word.get('word', word.get('text'))))
        tokens = _tokens(segment['text'], terms + word_terms)
        lines = _lines(tokens, max_chars)
        if any(len(token) > max_chars for token in tokens):
            warnings.append('原稿第 %d 塊：完整詞組超過每行字數，已保留詞組。' % number)
        groups = [(0, len(tokens))]
        boundaries = None
        if len(lines) > max_lines:
            boundaries = _timing_boundaries(segment, tokens)
            groups = []
            position = 0
            while boundaries and position < len(tokens):
                remaining = _lines(tokens[position:], max_chars)
                if len(remaining) <= max_lines:
                    groups.append((position, len(tokens)))
                    break
                capacity = position + remaining[max_lines - 1][1]
                previous_time = start if position == 0 else boundaries[position]
                candidates = [i for i in boundaries if position < i <= capacity and i < len(tokens)
                              and previous_time < boundaries[i] < end]
                if not candidates:
                    groups = []
                    break
                # Prefer clause endings, otherwise the latest reliable word boundary.
                natural = [i for i in candidates if tokens[i - 1][-1:] in '，。！？；：,.!?;:']
                pause_times = {a['end'] for a, b in zip(segment['words'], segment['words'][1:])
                               if b['start'] - a['end'] >= .35}
                pauses = [i for i in candidates if boundaries[i] in pause_times]
                stop = max(natural or pauses or candidates)
                groups.append((position, stop))
                position = stop
            if not groups:
                groups = [(0, len(tokens))]
                warnings.append('原稿第 %d 塊：缺少可靠且足夠的逐詞時間，保留原時間與全部文字；行數超過設定。' % number)
        # Clause splitting is independent of line capacity: two readable clauses
        # can appear sequentially even if both fit in one two-line caption.
        if split_clauses:
            boundaries = boundaries or _timing_boundaries(segment, tokens)
            if boundaries:
                expanded = []
                for left, right in groups:
                    position = left
                    for cut in sorted(i for i in boundaries if left < i < right and _break_score(tokens, i) >= 6):
                        prefix = _canonical(''.join(tokens[position:cut]))
                        suffix = _canonical(''.join(tokens[cut:right]))
                        previous_time = start if position == 0 else boundaries[position]
                        final_time = end if right == len(tokens) else boundaries[right]
                        if len(prefix) < 6 or len(suffix) < 6:
                            continue
                        if boundaries[cut] - previous_time < .75 or final_time - boundaries[cut] < .75:
                            continue
                        expanded.append((position, cut))
                        position = cut
                    expanded.append((position, right))
                groups = expanded
        cue_start = start
        for index, (left, right) in enumerate(groups):
            cue_end = end if index == len(groups) - 1 else boundaries[right]
            cue = dict(segment)
            cue.update(start=cue_start, end=cue_end, source_index=number,
                       text='\n'.join(line[2] for line in _lines(tokens[left:right], max_chars)))
            if len(groups) > 1:
                begin_offset = len(_canonical(''.join(tokens[:left])))
                end_offset = len(_canonical(''.join(tokens[:right])))
                word_offset = 0
                cue['words'] = []
                for word in segment['words']:
                    next_offset = word_offset + len(_canonical(word.get('word', word.get('text'))))
                    if word_offset >= begin_offset and next_offset <= end_offset:
                        cue['words'].append(dict(word))
                    word_offset = next_offset
            output.append(cue)
            if len(_canonical(cue['text'])) / (cue_end - cue_start) > 15:
                warnings.append('原稿第 %d 塊：閱讀速度偏快，建議預覽確認。' % number)
            cue_start = cue_end
    return output, warnings


def has_split_timing(cue):
    """Whether at least one interior cursor boundary can be proven from word times."""
    try:
        boundaries = _timing_boundaries(cue, list(cue['text']))
        return bool(boundaries and any(cue['start'] < value < cue['end']
                                       and _canonical(cue['text'][:index])
                                       and _canonical(cue['text'][index:])
                                       for index, value in boundaries.items()))
    except (KeyError, TypeError, ValueError):
        return False


def split_subtitle_at(cue, char_index):
    """Split at an exact text cursor position only when word timing proves it safe."""
    if not isinstance(cue, dict) or not isinstance(cue.get('text'), str):
        raise ValueError('字幕內容格式無效。')
    text = cue['text']
    if isinstance(char_index, bool) or not isinstance(char_index, int) or not 0 < char_index < len(text):
        raise ValueError('請將游標放在字幕中間的切句位置。')
    start, end = cue.get('start'), cue.get('end')
    if not _number(start) or not _number(end) or start < 0 or end <= start:
        raise ValueError('字幕時間無效，無法安全切句。')
    prefix, suffix = text[:char_index], text[char_index:]
    if not _canonical(prefix) or not _canonical(suffix):
        raise ValueError('切句位置兩側都需要有文字。')
    boundaries = _timing_boundaries(cue, [prefix, suffix])
    if not boundaries or 1 not in boundaries or not start < boundaries[1] < end:
        raise ValueError('此位置沒有可靠的逐詞時間，請選擇詞語之間的切點。')
    split_offset = len(_canonical(prefix))
    first, second = dict(cue), dict(cue)
    first.update(text=prefix, end=boundaries[1], words=[])
    second.update(text=suffix, start=boundaries[1], words=[])
    consumed = 0
    for word in cue['words']:
        target = first if consumed < split_offset else second
        target['words'].append(dict(word))
        consumed += len(_canonical(word.get('word', word.get('text'))))
    return [first, second]
