export interface SerializedMentionOccurrence {
  key: string;
  user_id: string;
  start: number;
  end: number;
  label: string;
}

export interface MentionOccurrence {
  key: string;
  userId: string;
  start: number;
  end: number;
  label: string;
}

export interface MentionSuggestion {
  id: string;
  label: string;
  email: string;
  username?: string;
}

export interface MentionedUser {
  email: string;
}

export interface MentionQuery {
  start: number;
  end: number;
  query: string;
}

export interface CommentTextPart {
  text: string;
  mention?: MentionOccurrence;
}

interface MentionRange {
  key: string;
  start: number;
  end: number;
}

const compareMentionRanges = (left: MentionRange, right: MentionRange) => {
  if (left.start !== right.start) {
    return left.start - right.start;
  }

  if (left.end !== right.end) {
    return left.end - right.end;
  }

  if (left.key < right.key) {
    return -1;
  }

  if (left.key > right.key) {
    return 1;
  }

  return 0;
};

export function deserializeMentionOccurrences(
  values: readonly SerializedMentionOccurrence[],
): MentionOccurrence[] {
  return values
    .map(({ key, user_id: userId, start, end, label }) => ({
      key,
      userId,
      start,
      end,
      label,
    }))
    .sort(compareMentionRanges);
}

export function serializeMentionOccurrences(
  values: readonly MentionOccurrence[],
): SerializedMentionOccurrence[] {
  return values
    .map(({ key, userId, start, end, label }) => ({
      key,
      user_id: userId,
      start,
      end,
      label,
    }))
    .sort(compareMentionRanges);
}

const mentionTokenAtEnd = /[\p{L}\p{N}_.+'@-]+$/u;

export function findMentionQuery(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): MentionQuery | null {
  if (
    !Number.isInteger(selectionStart) ||
    !Number.isInteger(selectionEnd) ||
    selectionStart !== selectionEnd ||
    selectionStart < 0 ||
    selectionStart > value.length
  ) {
    return null;
  }

  const match = mentionTokenAtEnd.exec(value.slice(0, selectionStart));
  if (!match || !match[0].startsWith('@')) {
    return null;
  }

  const query = match[0].slice(1);
  if (query.length < 1 || query.length > 64) {
    return null;
  }

  return {
    start: selectionStart - match[0].length,
    end: selectionStart,
    query,
  };
}

const isHighSurrogate = (codeUnit: number) =>
  codeUnit >= 0xd800 && codeUnit <= 0xdbff;

const isLowSurrogate = (codeUnit: number) =>
  codeUnit >= 0xdc00 && codeUnit <= 0xdfff;

const isSurrogateBoundary = (value: string, offset: number) =>
  offset === 0 ||
  offset === value.length ||
  !(
    isHighSurrogate(value.charCodeAt(offset - 1)) &&
    isLowSurrogate(value.charCodeAt(offset))
  );

const hasValidMentionRanges = (
  value: string,
  mentions: readonly MentionOccurrence[],
) => {
  let previousEnd = 0;

  for (const mention of mentions) {
    if (
      !Number.isInteger(mention.start) ||
      !Number.isInteger(mention.end) ||
      mention.start < 0 ||
      mention.start >= mention.end ||
      mention.end > value.length ||
      mention.start < previousEnd ||
      !isSurrogateBoundary(value, mention.start) ||
      !isSurrogateBoundary(value, mention.end) ||
      value.slice(mention.start, mention.end) !== mention.label
    ) {
      return false;
    }

    previousEnd = mention.end;
  }

  return true;
};

export function splitTextByMentions(
  value: string,
  mentions: readonly MentionOccurrence[],
): CommentTextPart[] {
  if (!hasValidMentionRanges(value, mentions)) {
    return [{ text: value }];
  }

  const parts: CommentTextPart[] = [];
  let cursor = 0;

  for (const mention of mentions) {
    if (mention.start > cursor) {
      parts.push({ text: value.slice(cursor, mention.start) });
    }

    parts.push({
      text: value.slice(mention.start, mention.end),
      mention,
    });
    cursor = mention.end;
  }

  if (cursor < value.length || parts.length === 0) {
    parts.push({ text: value.slice(cursor) });
  }

  return parts;
}
