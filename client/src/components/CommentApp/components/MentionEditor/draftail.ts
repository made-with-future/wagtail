import type {
  MentionOccurrence,
  MentionQuery,
  MentionSuggestion,
} from '../../utils/mentions';
import {
  ContentBlock,
  ContentState,
  EditorState,
  Modifier,
  SelectionState,
} from 'draft-js';
import { v4 as uuidv4 } from 'uuid';

import { findMentionQuery } from '../../utils/mentions';

export interface MentionEditorValue {
  value: string;
  mentions: MentionOccurrence[];
}

interface BlockRange {
  block: ContentBlock;
  start: number;
  end: number;
}

interface MentionEntityData {
  key: string;
  userId: string;
  label: string;
}

const MENTION_ENTITY_TYPE = 'MENTION';

const getBlockRanges = (content: ContentState): BlockRange[] => {
  const blocks = content.getBlockMap().toArray();
  let start = 0;

  return blocks.map((block, index) => {
    const range = { block, start, end: start + block.getLength() };
    start = range.end + (index === blocks.length - 1 ? 0 : 1);
    return range;
  });
};

const isHighSurrogate = (codeUnit: number) =>
  codeUnit >= 0xd800 && codeUnit <= 0xdbff;

const isLowSurrogate = (codeUnit: number) =>
  codeUnit >= 0xdc00 && codeUnit <= 0xdfff;

const isUtf16Boundary = (value: string, offset: number) =>
  offset === 0 ||
  offset === value.length ||
  !(
    isHighSurrogate(value.charCodeAt(offset - 1)) &&
    isLowSurrogate(value.charCodeAt(offset))
  );

const compareMentions = (left: MentionOccurrence, right: MentionOccurrence) => {
  if (left.start !== right.start) return left.start - right.start;
  if (left.end !== right.end) return left.end - right.end;
  return left.key.localeCompare(right.key);
};

const findContainingBlock = (
  ranges: readonly BlockRange[],
  start: number,
  end: number,
) => ranges.find((range) => start >= range.start && end <= range.end);

const validateMentions = (
  value: string,
  mentions: readonly MentionOccurrence[],
  blockRanges: readonly BlockRange[],
) => {
  const keys = new Set<string>();
  let previous: MentionOccurrence | null = null;

  for (const mention of mentions) {
    if (
      typeof mention.key !== 'string' ||
      typeof mention.userId !== 'string' ||
      typeof mention.label !== 'string' ||
      keys.has(mention.key) ||
      !Number.isInteger(mention.start) ||
      !Number.isInteger(mention.end) ||
      mention.start < 0 ||
      mention.start >= mention.end ||
      mention.end > value.length ||
      !isUtf16Boundary(value, mention.start) ||
      !isUtf16Boundary(value, mention.end) ||
      value.slice(mention.start, mention.end) !== mention.label ||
      findContainingBlock(blockRanges, mention.start, mention.end) ===
        undefined ||
      (previous !== null &&
        (compareMentions(previous, mention) > 0 ||
          mention.start < previous.end))
    ) {
      return false;
    }

    keys.add(mention.key);
    previous = mention;
  }

  return true;
};

const makeSelection = (block: ContentBlock, start: number, end: number) =>
  SelectionState.createEmpty(block.getKey()).merge({
    anchorOffset: start,
    focusOffset: end,
  }) as SelectionState;

const isMentionEntity = (content: ContentState, entityKey: string | null) =>
  entityKey !== null &&
  content.getEntity(entityKey).getType() === MENTION_ENTITY_TYPE;

export function createMentionEditorState(
  value: string,
  mentions: readonly MentionOccurrence[],
): EditorState {
  let content = ContentState.createFromText(value);
  const blockRanges = getBlockRanges(content);

  if (!validateMentions(value, mentions, blockRanges)) {
    return EditorState.createWithContent(content);
  }

  for (const mention of mentions) {
    const range = findContainingBlock(blockRanges, mention.start, mention.end);
    if (range !== undefined) {
      content = content.createEntity(MENTION_ENTITY_TYPE, 'MUTABLE', {
        key: mention.key,
        userId: mention.userId,
        label: mention.label,
      } satisfies MentionEntityData);
      content = Modifier.applyEntity(
        content,
        makeSelection(
          range.block,
          mention.start - range.start,
          mention.end - range.start,
        ),
        content.getLastCreatedEntityKey(),
      );
    }
  }

  return EditorState.createWithContent(content);
}

export function serializeMentionEditorState(
  editorState: EditorState,
): MentionEditorValue {
  const content = editorState.getCurrentContent();
  const value = content.getPlainText('\n');
  const blockRanges = getBlockRanges(content);
  const mentions: MentionOccurrence[] = [];

  for (const range of blockRanges) {
    range.block.findEntityRanges(
      (character) => isMentionEntity(content, character.getEntity()),
      (start, end) => {
        const entityKey = range.block.getCharacterList().get(start).getEntity();
        if (entityKey === null) return;

        const entity = content.getEntity(entityKey);
        const data = entity.getData() as Partial<MentionEntityData>;
        const label = range.block.getText().slice(start, end);
        if (
          typeof data.key !== 'string' ||
          typeof data.userId !== 'string' ||
          typeof data.label !== 'string' ||
          data.label !== label
        ) {
          return;
        }

        mentions.push({
          key: data.key,
          userId: data.userId,
          start: range.start + start,
          end: range.start + end,
          label: data.label,
        });
      },
    );
  }

  mentions.sort(compareMentions);
  return {
    value,
    mentions: validateMentions(value, mentions, blockRanges) ? mentions : [],
  };
}

export function normalizeMentionEditorState(
  editorState: EditorState,
): EditorState {
  const content = editorState.getCurrentContent();
  const entityRanges = new Map<
    string,
    Array<{ block: ContentBlock; start: number; end: number }>
  >();
  const invalidEntityKeys = new Set<string>();

  content
    .getBlockMap()
    .toArray()
    .forEach((block) => {
      block.findEntityRanges(
        (character) => isMentionEntity(content, character.getEntity()),
        (start, end) => {
          const entityKey = block.getCharacterList().get(start).getEntity();
          if (entityKey === null) return;

          const ranges = entityRanges.get(entityKey) || [];
          ranges.push({ block, start, end });
          entityRanges.set(entityKey, ranges);

          const data = content
            .getEntity(entityKey)
            .getData() as Partial<MentionEntityData>;
          if (
            typeof data.label !== 'string' ||
            block.getText().slice(start, end) !== data.label
          ) {
            invalidEntityKeys.add(entityKey);
          }
        },
      );
    });

  entityRanges.forEach((ranges, entityKey) => {
    if (ranges.length !== 1) invalidEntityKeys.add(entityKey);
  });

  if (invalidEntityKeys.size === 0) return editorState;

  let normalizedContent = content;
  invalidEntityKeys.forEach((entityKey) => {
    entityRanges.get(entityKey)?.forEach(({ block, start, end }) => {
      normalizedContent = Modifier.applyEntity(
        normalizedContent,
        makeSelection(block, start, end),
        null,
      );
    });
  });
  normalizedContent = normalizedContent.merge({
    selectionBefore: content.getSelectionBefore(),
    selectionAfter: content.getSelectionAfter(),
  }) as ContentState;

  return EditorState.set(editorState, {
    currentContent: normalizedContent,
  }) as EditorState;
}

export function getMentionQueryFromEditorState(
  editorState: EditorState,
): MentionQuery | null {
  const selection = editorState.getSelection();
  if (
    !selection.isCollapsed() ||
    selection.getAnchorKey() !== selection.getFocusKey()
  ) {
    return null;
  }

  const content = editorState.getCurrentContent();
  const range = getBlockRanges(content).find(
    ({ block }) => block.getKey() === selection.getAnchorKey(),
  );
  if (range === undefined) return null;

  const offset = range.start + selection.getAnchorOffset();
  const query = findMentionQuery(content.getPlainText('\n'), offset, offset);
  if (query === null) return null;

  const containsMentionEntity = range.block
    .getCharacterList()
    .slice(query.start - range.start, query.end - range.start)
    .some(
      (character) =>
        character !== undefined &&
        isMentionEntity(content, character.getEntity()),
    );

  return containsMentionEntity ? null : query;
}

export function insertMentionSuggestion(
  editorState: EditorState,
  query: MentionQuery,
  suggestion: MentionSuggestion,
  createKey: () => string = uuidv4,
): EditorState {
  const content = editorState.getCurrentContent();
  const value = content.getPlainText('\n');
  const range = findContainingBlock(
    getBlockRanges(content),
    query.start,
    query.end,
  );
  if (
    range === undefined ||
    query.start < 0 ||
    query.end > value.length ||
    value.slice(query.start, query.end) !== `@${query.query}`
  ) {
    return editorState;
  }

  let nextContent = content.createEntity(MENTION_ENTITY_TYPE, 'MUTABLE', {
    key: createKey(),
    userId: suggestion.id,
    label: suggestion.label,
  } satisfies MentionEntityData);
  const entityKey = nextContent.getLastCreatedEntityKey();
  const blockStart = query.start - range.start;
  const querySelection = makeSelection(
    range.block,
    blockStart,
    query.end - range.start,
  );
  nextContent = Modifier.replaceText(
    nextContent,
    querySelection,
    `${suggestion.label} `,
    editorState.getCurrentInlineStyle(),
    undefined,
  );
  nextContent = Modifier.applyEntity(
    nextContent,
    makeSelection(
      nextContent.getBlockForKey(range.block.getKey()),
      blockStart,
      blockStart + suggestion.label.length,
    ),
    entityKey,
  );

  const pushed = EditorState.push(editorState, nextContent, 'apply-entity');
  const caret = blockStart + suggestion.label.length + 1;
  return EditorState.forceSelection(
    pushed,
    makeSelection(
      nextContent.getBlockForKey(range.block.getKey()),
      caret,
      caret,
    ),
  );
}
