import type {
  MentionOccurrence,
  MentionSuggestion,
} from '../../utils/mentions';
import { ContentBlock, EditorState, Modifier, SelectionState } from 'draft-js';

import {
  createCommentEditorState,
  getMentionQueryFromEditorState,
  insertMentionSuggestion,
  normalizeCommentEditorState,
  serializeCommentEditorState,
} from './draftail';

const occurrence = (
  value: string,
  key: string,
  userId: string,
  label: string,
  from = 0,
): MentionOccurrence => {
  const start = value.indexOf(label, from);
  return { key, userId, start, end: start + label.length, label };
};

const selection = (
  block: ContentBlock,
  start: number,
  end = start,
): SelectionState =>
  SelectionState.createEmpty(block.getKey()).merge({
    anchorOffset: start,
    focusOffset: end,
    hasFocus: true,
  }) as SelectionState;

const firstBlock = (state: EditorState) =>
  state.getCurrentContent().getFirstBlock();

const pushContent = (
  state: EditorState,
  content: ReturnType<EditorState['getCurrentContent']>,
  changeType: Parameters<typeof EditorState.push>[2],
) => EditorState.push(state, content, changeType);

test('hydrates and serializes plain multiline UTF-16 text deterministically', () => {
  const value = '😀 Hello @Ada\n@Ada and @Ada';
  const first = occurrence(value, 'first', '7', '@Ada');
  const second = occurrence(value, 'second', '7', '@Ada', first.end);
  const third = occurrence(value, 'third', '8', '@Ada', second.end);

  const state = createCommentEditorState(value, [first, second, third]);

  expect(state.getCurrentContent().getBlockMap().size).toBe(2);
  expect(serializeCommentEditorState(state)).toEqual({
    value,
    mentions: [first, second, third],
  });
  const entityKeys = state
    .getCurrentContent()
    .getBlockMap()
    .toArray()
    .flatMap((block) =>
      block
        .getCharacterList()
        .toArray()
        .map((item) => item.getEntity()),
    )
    .filter((key) => key !== null);
  expect(new Set(entityKeys).size).toBe(3);
});

test.each([
  [
    'canonical order',
    'First @Ada then @Bea',
    [
      { key: 'b', userId: '8', start: 16, end: 20, label: '@Bea' },
      { key: 'a', userId: '7', start: 6, end: 10, label: '@Ada' },
    ],
  ],
  [
    'unique keys',
    '@Ada @Bea',
    [
      { key: 'same', userId: '7', start: 0, end: 4, label: '@Ada' },
      { key: 'same', userId: '8', start: 5, end: 9, label: '@Bea' },
    ],
  ],
  [
    'non-overlap',
    '@AdaBea',
    [
      { key: 'a', userId: '7', start: 0, end: 4, label: '@Ada' },
      { key: 'b', userId: '8', start: 3, end: 7, label: 'aBea' },
    ],
  ],
  [
    'bounds',
    '@Ada',
    [{ key: 'a', userId: '7', start: 0, end: 5, label: '@Ada!' }],
  ],
  [
    'UTF-16 boundaries',
    '😀 @Ada',
    [{ key: 'a', userId: '7', start: 1, end: 2, label: '\ude00' }],
  ],
  [
    'one block containment',
    '@Ada\n@Bea',
    [{ key: 'a', userId: '7', start: 0, end: 10, label: '@Ada\n@Bea' }],
  ],
  [
    'label slices',
    '@Ada',
    [{ key: 'a', userId: '7', start: 0, end: 4, label: '@Bea' }],
  ],
])(
  'invalid %s rejects the complete hydration before applying entities',
  (_name, value, mentions) => {
    const state = createCommentEditorState(
      value,
      mentions as MentionOccurrence[],
    );

    expect(serializeCommentEditorState(state)).toEqual({
      value,
      mentions: [],
    });
    state
      .getCurrentContent()
      .getBlockMap()
      .toArray()
      .forEach((block) =>
        block
          .getCharacterList()
          .toArray()
          .forEach((character) => expect(character.getEntity()).toBeNull()),
      );
  },
);

test('extracts mention queries only from a collapsed Draft selection', () => {
  const state = createCommentEditorState('Hello @ada', []);
  const block = firstBlock(state);
  const collapsed = EditorState.forceSelection(state, selection(block, 10));
  const selected = EditorState.forceSelection(state, selection(block, 7, 10));

  expect(getMentionQueryFromEditorState(collapsed)).toEqual({
    start: 6,
    end: 10,
    query: 'ada',
  });
  expect(getMentionQueryFromEditorState(selected)).toBeNull();
});

test('ignores a mention query when the caret is inside its live entity', () => {
  const value = 'Hello @Ada';
  const state = createCommentEditorState(value, [
    occurrence(value, 'ada', '7', '@Ada'),
  ]);
  const block = firstBlock(state);
  const selected = EditorState.forceSelection(state, selection(block, 8));

  expect(getMentionQueryFromEditorState(selected)).toBeNull();
});

test('ignores a mention query at its half-open end after deleting its trailing space', () => {
  const state = createCommentEditorState('@ad', []);
  const block = firstBlock(state);
  const selected = EditorState.forceSelection(state, selection(block, 3));
  const inserted = insertMentionSuggestion(
    selected,
    { start: 0, end: 3, query: 'ad' },
    { id: '7', label: '@Ada', email: 'ada@example.com' },
    () => 'mention-ada',
  );
  const insertedBlock = firstBlock(inserted);
  const withoutSpaceContent = Modifier.removeRange(
    inserted.getCurrentContent(),
    selection(insertedBlock, 4, 5),
    'backward',
  );
  const withoutSpace = normalizeCommentEditorState(
    pushContent(inserted, withoutSpaceContent, 'backspace-character'),
  );
  const withoutSpaceBlock = firstBlock(withoutSpace);
  const atEntityEnd = EditorState.forceSelection(
    withoutSpace,
    selection(withoutSpaceBlock, 4),
  );

  expect(serializeCommentEditorState(atEntityEnd)).toEqual({
    value: '@Ada',
    mentions: [
      {
        key: 'mention-ada',
        userId: '7',
        start: 0,
        end: 4,
        label: '@Ada',
      },
    ],
  });
  expect(getMentionQueryFromEditorState(atEntityEnd)).toBeNull();
});

test('ignores a query extended past a live mention by adjacent token characters', () => {
  const value = '@Adaextra';
  const state = createCommentEditorState(value, [
    occurrence(value, 'ada', '7', '@Ada'),
  ]);
  const block = firstBlock(state);
  const selected = EditorState.forceSelection(
    state,
    selection(block, value.length),
  );

  expect(getMentionQueryFromEditorState(selected)).toBeNull();
});

test('recognizes query-shaped text after normalization removes its mismatched entity', () => {
  const value = 'Hello @Ada';
  const state = createCommentEditorState(value, [
    occurrence(value, 'ada', '7', '@Ada'),
  ]);
  const block = firstBlock(state);
  const changedContent = Modifier.replaceText(
    state.getCurrentContent(),
    selection(block, 8, 9),
    'x',
  );
  const normalized = normalizeCommentEditorState(
    pushContent(state, changedContent, 'insert-characters'),
  );
  const normalizedBlock = firstBlock(normalized);
  const selected = EditorState.forceSelection(
    normalized,
    selection(normalizedBlock, normalizedBlock.getLength()),
  );

  expect(getMentionQueryFromEditorState(selected)).toEqual({
    start: 6,
    end: 10,
    query: 'Axa',
  });
});

test('inserts one mutable entity and an unlinked trailing space in one undo step', () => {
  const state = createCommentEditorState('Hello @ad world', []);
  const block = firstBlock(state);
  const selected = EditorState.forceSelection(state, selection(block, 9));
  const suggestion: MentionSuggestion = {
    id: '7',
    label: '@Ada',
    email: 'ada@example.com',
  };

  const inserted = insertMentionSuggestion(
    selected,
    { start: 6, end: 9, query: 'ad' },
    suggestion,
    () => 'mention-ada',
  );

  expect(serializeCommentEditorState(inserted)).toEqual({
    value: 'Hello @Ada  world',
    mentions: [
      {
        key: 'mention-ada',
        userId: '7',
        start: 6,
        end: 10,
        label: '@Ada',
      },
    ],
  });
  const mentionEntityKey = firstBlock(inserted)
    .getCharacterList()
    .get(6)
    .getEntity();
  expect(mentionEntityKey).not.toBeNull();
  expect(
    inserted
      .getCurrentContent()
      .getEntity(mentionEntityKey as string)
      .getMutability(),
  ).toBe('MUTABLE');
  expect(
    firstBlock(inserted).getCharacterList().get(10).getEntity(),
  ).toBeNull();
  expect(inserted.getLastChangeType()).toBe('apply-entity');
  expect(serializeCommentEditorState(EditorState.undo(inserted))).toEqual({
    value: 'Hello @ad world',
    mentions: [],
  });
  expect(
    serializeCommentEditorState(EditorState.redo(EditorState.undo(inserted))),
  ).toEqual(serializeCommentEditorState(inserted));
});

test('plain edits before and after entities update ranges without losing identity', () => {
  const value = 'Hello @Ada';
  const ada = occurrence(value, 'ada', '7', '@Ada');
  const hydrated = createCommentEditorState(value, [ada]);
  const block = firstBlock(hydrated);
  const beforeContent = Modifier.insertText(
    hydrated.getCurrentContent(),
    selection(block, 0),
    'Well, ',
  );
  const before = pushContent(hydrated, beforeContent, 'insert-characters');
  const beforeBlock = firstBlock(before);
  const afterContent = Modifier.insertText(
    before.getCurrentContent(),
    selection(beforeBlock, beforeBlock.getLength()),
    '!',
  );
  const after = pushContent(before, afterContent, 'insert-characters');

  expect(serializeCommentEditorState(after)).toEqual({
    value: 'Well, Hello @Ada!',
    mentions: [{ ...ada, start: 12, end: 16 }],
  });
});

test('partial edits preserve characters but normalization removes the whole identity in the same undo frame', () => {
  const value = 'Hello @Ada';
  const ada = occurrence(value, 'ada', '7', '@Ada');
  const hydrated = createCommentEditorState(value, [ada]);
  const block = firstBlock(hydrated);
  const changedContent = Modifier.replaceText(
    hydrated.getCurrentContent(),
    selection(block, 8, 9),
    'x',
  );
  const changed = pushContent(hydrated, changedContent, 'insert-characters');

  const normalized = normalizeCommentEditorState(changed);

  expect(serializeCommentEditorState(normalized)).toEqual({
    value: 'Hello @Axa',
    mentions: [],
  });
  expect(normalized.getUndoStack()).toBe(changed.getUndoStack());
  expect(serializeCommentEditorState(EditorState.undo(normalized))).toEqual({
    value,
    mentions: [ada],
  });
});

test('consecutive typing after normalization remains one undo and redo step', () => {
  const value = 'Hello @Ada';
  const ada = occurrence(value, 'ada', '7', '@Ada');
  const hydrated = createCommentEditorState(value, [ada]);
  const block = firstBlock(hydrated);
  const firstContent = Modifier.replaceText(
    hydrated.getCurrentContent(),
    selection(block, 8, 9),
    'x',
  );
  const first = normalizeCommentEditorState(
    pushContent(hydrated, firstContent, 'insert-characters'),
  );
  const secondContent = Modifier.insertText(
    first.getCurrentContent(),
    first.getSelection(),
    'y',
  );
  const second = normalizeCommentEditorState(
    pushContent(first, secondContent, 'insert-characters'),
  );

  expect(serializeCommentEditorState(second)).toEqual({
    value: 'Hello @Axya',
    mentions: [],
  });
  const undone = EditorState.undo(second);
  expect(serializeCommentEditorState(undone)).toEqual({
    value,
    mentions: [ada],
  });
  expect(serializeCommentEditorState(EditorState.redo(undone))).toEqual(
    serializeCommentEditorState(second),
  );
});

test('cut, selected replacement, and plain-text paste transform text and entities', () => {
  const value = 'Start @Ada end';
  const ada = occurrence(value, 'ada', '7', '@Ada');
  const hydrated = createCommentEditorState(value, [ada]);
  const block = firstBlock(hydrated);

  const cutContent = Modifier.removeRange(
    hydrated.getCurrentContent(),
    selection(block, 6, 10),
    'forward',
  );
  const cut = normalizeCommentEditorState(
    pushContent(hydrated, cutContent, 'remove-range'),
  );
  expect(serializeCommentEditorState(cut)).toEqual({
    value: 'Start  end',
    mentions: [],
  });

  const replacedContent = Modifier.replaceText(
    hydrated.getCurrentContent(),
    selection(block, 7, 9),
    'XX',
  );
  const replaced = normalizeCommentEditorState(
    pushContent(hydrated, replacedContent, 'insert-characters'),
  );
  expect(serializeCommentEditorState(replaced)).toEqual({
    value: 'Start @XXa end',
    mentions: [],
  });

  const pastedContent = Modifier.insertText(
    hydrated.getCurrentContent(),
    selection(block, 0),
    'Pasted\n',
  );
  const pasted = pushContent(hydrated, pastedContent, 'insert-characters');
  expect(serializeCommentEditorState(pasted)).toEqual({
    value: 'Pasted\nStart @Ada end',
    mentions: [{ ...ada, start: ada.start + 7, end: ada.end + 7 }],
  });
});
