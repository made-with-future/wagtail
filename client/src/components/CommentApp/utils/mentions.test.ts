import {
  MentionOccurrence,
  MentionSuggestion,
  MentionedUser,
  SerializedMentionOccurrence,
  deserializeMentionOccurrences,
  findMentionQuery,
  serializeMentionOccurrences,
  splitTextByMentions,
} from './mentions';

describe('mention occurrence wire conversion', () => {
  test('deserializes snake_case values and sorts by start, end, and key', () => {
    const values: readonly SerializedMentionOccurrence[] = [
      { key: 'later', user_id: '3', start: 12, end: 17, label: '@Kim' },
      { key: 'b', user_id: '2', start: 2, end: 7, label: '@Alex' },
      { key: 'longer', user_id: '1', start: 2, end: 8, label: '@Alexa' },
      { key: 'a', user_id: '1', start: 2, end: 7, label: '@Alex' },
    ];

    expect(deserializeMentionOccurrences(values)).toEqual([
      { key: 'a', userId: '1', start: 2, end: 7, label: '@Alex' },
      { key: 'b', userId: '2', start: 2, end: 7, label: '@Alex' },
      { key: 'longer', userId: '1', start: 2, end: 8, label: '@Alexa' },
      { key: 'later', userId: '3', start: 12, end: 17, label: '@Kim' },
    ]);
    expect(values[0].key).toBe('later');
  });

  test('serializes camelCase values in canonical order', () => {
    const values: readonly MentionOccurrence[] = [
      { key: '2', userId: '8', start: 11, end: 15, label: '@Lee' },
      { key: 'b', userId: '7', start: 0, end: 4, label: '@Sam' },
      { key: 'a', userId: '7', start: 0, end: 4, label: '@Sam' },
    ];

    expect(serializeMentionOccurrences(values)).toEqual([
      { key: 'a', user_id: '7', start: 0, end: 4, label: '@Sam' },
      { key: 'b', user_id: '7', start: 0, end: 4, label: '@Sam' },
      { key: '2', user_id: '8', start: 11, end: 15, label: '@Lee' },
    ]);
    expect(values[0].key).toBe('2');
  });

  test('round-trips repeated occurrences, duplicate labels, and duplicate users', () => {
    const values: readonly MentionOccurrence[] = [
      { key: 'third', userId: '7', start: 20, end: 24, label: '@Sam' },
      { key: 'first', userId: '7', start: 0, end: 4, label: '@Sam' },
      { key: 'second', userId: '8', start: 10, end: 14, label: '@Sam' },
    ];

    expect(
      deserializeMentionOccurrences(serializeMentionOccurrences(values)),
    ).toEqual([
      { key: 'first', userId: '7', start: 0, end: 4, label: '@Sam' },
      { key: 'second', userId: '8', start: 10, end: 14, label: '@Sam' },
      { key: 'third', userId: '7', start: 20, end: 24, label: '@Sam' },
    ]);
  });

  test('keeps email metadata separate from saved identity and label data', () => {
    const suggestion: MentionSuggestion = {
      id: '7',
      label: 'Sam Lee',
      email: 'sam@example.com',
      username: 'sam',
    };
    const mentionedUser: MentionedUser = { email: suggestion.email };
    const occurrence: MentionOccurrence = {
      key: 'first',
      userId: suggestion.id,
      start: 0,
      end: 8,
      label: `@${suggestion.label}`,
    };

    const [serialized] = serializeMentionOccurrences([occurrence]);

    expect(serialized).toEqual({
      key: 'first',
      user_id: '7',
      start: 0,
      end: 8,
      label: '@Sam Lee',
    });
    expect(serialized).not.toHaveProperty('email');
    expect(mentionedUser).toEqual({ email: 'sam@example.com' });
  });
});

describe('splitTextByMentions', () => {
  test('uses UTF-16 offsets to split repeated mentions across emoji and lines', () => {
    const value = `Hi \u{1f600}\n@Ada and @Ada`;
    const mentions: readonly MentionOccurrence[] = [
      { key: 'first', userId: '7', start: 6, end: 10, label: '@Ada' },
      { key: 'second', userId: '7', start: 15, end: 19, label: '@Ada' },
    ];

    expect(splitTextByMentions(value, mentions)).toEqual([
      { text: `Hi \u{1f600}\n` },
      { text: '@Ada', mention: mentions[0] },
      { text: ' and ' },
      { text: '@Ada', mention: mentions[1] },
    ]);
  });

  test('accepts adjacent, monotonically sorted non-overlapping mentions', () => {
    const value = '@Ada@Bob';
    const mentions: readonly MentionOccurrence[] = [
      { key: 'ada', userId: '1', start: 0, end: 4, label: '@Ada' },
      { key: 'bob', userId: '2', start: 4, end: 8, label: '@Bob' },
    ];

    expect(splitTextByMentions(value, mentions)).toEqual([
      { text: '@Ada', mention: mentions[0] },
      { text: '@Bob', mention: mentions[1] },
    ]);
  });

  test('returns the text as one plain part when no mentions are supplied', () => {
    expect(splitTextByMentions('Plain text', [])).toEqual([
      { text: 'Plain text' },
    ]);
  });

  test.each<[string, MentionOccurrence]>([
    [
      'a fractional start',
      { key: 'bad', userId: '1', start: 0.5, end: 4, label: '@Ada' },
    ],
    [
      'a fractional end',
      { key: 'bad', userId: '1', start: 0, end: 3.5, label: '@Ad' },
    ],
    [
      'a non-finite start',
      { key: 'bad', userId: '1', start: Number.NaN, end: 4, label: '@Ada' },
    ],
    [
      'a negative start that slice would clamp',
      { key: 'bad', userId: '1', start: -4, end: 4, label: '@Ada' },
    ],
    [
      'an end beyond the text that slice would clamp',
      { key: 'bad', userId: '1', start: 0, end: 40, label: '@Ada' },
    ],
    [
      'an empty range',
      { key: 'bad', userId: '1', start: 2, end: 2, label: '' },
    ],
    [
      'a reversed range',
      { key: 'bad', userId: '1', start: 3, end: 2, label: '' },
    ],
  ])('rejects %s without normalizing its range', (_name, mention) => {
    expect(splitTextByMentions('@Ada', [mention])).toEqual([{ text: '@Ada' }]);
  });

  test('rejects start and end offsets that split a surrogate pair', () => {
    const value = `A\u{1f600}B`;
    const splitStart: MentionOccurrence = {
      key: 'start',
      userId: '1',
      start: 2,
      end: 3,
      label: value.slice(2, 3),
    };
    const splitEnd: MentionOccurrence = {
      key: 'end',
      userId: '1',
      start: 1,
      end: 2,
      label: value.slice(1, 2),
    };

    expect(splitTextByMentions(value, [splitStart])).toEqual([{ text: value }]);
    expect(splitTextByMentions(value, [splitEnd])).toEqual([{ text: value }]);
  });

  test('accepts a range aligned around a complete surrogate pair', () => {
    const value = `A\u{1f600}B`;
    const mention: MentionOccurrence = {
      key: 'emoji',
      userId: '1',
      start: 1,
      end: 3,
      label: '\u{1f600}',
    };

    expect(splitTextByMentions(value, [mention])).toEqual([
      { text: 'A' },
      { text: '\u{1f600}', mention },
      { text: 'B' },
    ]);
  });

  test('requires the exact text slice to match the saved label', () => {
    const mention: MentionOccurrence = {
      key: 'wrong-label',
      userId: '1',
      start: 0,
      end: 4,
      label: '@Bob',
    };

    expect(splitTextByMentions('@Ada', [mention])).toEqual([{ text: '@Ada' }]);
  });

  test('rejects overlapping occurrences', () => {
    const value = '@Ada';
    const mentions: readonly MentionOccurrence[] = [
      { key: 'outer', userId: '1', start: 0, end: 4, label: '@Ada' },
      { key: 'inner', userId: '1', start: 1, end: 4, label: 'Ada' },
    ];

    expect(splitTextByMentions(value, mentions)).toEqual([{ text: value }]);
  });

  test('rejects valid non-overlapping occurrences supplied out of order', () => {
    const value = '@Ada @Bob';
    const mentions: readonly MentionOccurrence[] = [
      { key: 'bob', userId: '2', start: 5, end: 9, label: '@Bob' },
      { key: 'ada', userId: '1', start: 0, end: 4, label: '@Ada' },
    ];

    expect(splitTextByMentions(value, mentions)).toEqual([{ text: value }]);
  });

  test('does not render a valid prefix when a later occurrence is invalid', () => {
    const value = '@Ada and @Bob';
    const mentions: readonly MentionOccurrence[] = [
      { key: 'ada', userId: '1', start: 0, end: 4, label: '@Ada' },
      { key: 'bob', userId: '2', start: 9, end: 13, label: '@Rob' },
    ];

    expect(splitTextByMentions(value, mentions)).toEqual([{ text: value }]);
  });
});

describe('findMentionQuery', () => {
  test('finds a collapsed query whose trigger starts the value', () => {
    expect(findMentionQuery('@ada', 4, 4)).toEqual({
      start: 0,
      end: 4,
      query: 'ada',
    });
  });

  test('finds a collapsed query at a caret in the middle of the value', () => {
    const value = 'Review @ada later';

    expect(findMentionQuery(value, 11, 11)).toEqual({
      start: 7,
      end: 11,
      query: 'ada',
    });
  });

  test('returns null for a caret at the beginning or a non-collapsed selection', () => {
    expect(findMentionQuery('@ada', 0, 0)).toBeNull();
    expect(findMentionQuery('@ada', 2, 4)).toBeNull();
  });

  test.each(['_', '.', '+', '-', "'", '@'])(
    'accepts %s inside the query token',
    (punctuation) => {
      const query = `a${punctuation}b`;
      const value = `@${query}`;

      expect(findMentionQuery(value, value.length, value.length)).toEqual({
        start: 0,
        end: value.length,
        query,
      });
    },
  );

  test('accepts Unicode letters and numbers, including an astral letter', () => {
    const query = `\u00c9lodie\u0662\u{10400}`;
    const value = `@${query}`;

    expect(findMentionQuery(value, value.length, value.length)).toEqual({
      start: 0,
      end: value.length,
      query,
    });
  });

  test('requires the trigger to start a maximal token run', () => {
    const email = 'person@example.com';

    expect(findMentionQuery(email, email.length, email.length)).toBeNull();
    expect(findMentionQuery('word@ada', 8, 8)).toBeNull();
  });

  test('accepts a trigger preceded by a non-token boundary', () => {
    const value = 'Review (@ada';

    expect(findMentionQuery(value, value.length, value.length)).toEqual({
      start: 8,
      end: value.length,
      query: 'ada',
    });
  });

  test.each([' ', '\t', '\n', '!', '/', ':'])(
    'returns null after the query is terminated by %p',
    (terminator) => {
      const value = `@ada${terminator}`;

      expect(findMentionQuery(value, value.length, value.length)).toBeNull();
    },
  );

  test('returns null for a bare trigger', () => {
    expect(findMentionQuery('@', 1, 1)).toBeNull();
  });

  test('accepts exactly one UTF-16 unit after the trigger', () => {
    expect(findMentionQuery('@a', 2, 2)).toEqual({
      start: 0,
      end: 2,
      query: 'a',
    });
  });

  test('accepts 64 UTF-16 units including an astral character', () => {
    const query = `${'a'.repeat(62)}\u{10400}`;
    const value = `@${query}`;

    expect(query).toHaveLength(64);
    expect(findMentionQuery(value, value.length, value.length)).toEqual({
      start: 0,
      end: value.length,
      query,
    });
  });

  test('rejects 65 UTF-16 units including an astral character', () => {
    const query = `${'a'.repeat(63)}\u{10400}`;
    const value = `@${query}`;

    expect(query).toHaveLength(65);
    expect(findMentionQuery(value, value.length, value.length)).toBeNull();
  });
});
