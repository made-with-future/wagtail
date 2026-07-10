import type { SelectionState } from 'draft-js';
import type { EntityDecoratorProps, EntitySourceProps } from 'draftail';
import type { MentionOccurrence, MentionedUser } from '../../utils/mentions';
import { EditorState } from 'draft-js';
import { DraftailEditor } from 'draftail';
import React from 'react';

import { gettext } from '../../../../utils/gettext';
import { serializeMentionOccurrences } from '../../utils/mentions';
import { MentionSpan, MentionedUsersContext } from '../MentionText';
import {
  createMentionEditorState,
  getMentionQueryFromEditorState,
  insertMentionSuggestion,
  normalizeMentionEditorState,
  serializeMentionEditorState,
} from './draftail';
import { useMentionSuggestions } from './useMentionSuggestions';

export interface MentionEditorProps {
  id: string;
  label: string;
  value: string;
  mentions: readonly MentionOccurrence[];
  mentionedUsers: Readonly<Record<string, MentionedUser>>;
  mentionSuggestionsUrl?: string;
  error?: string;
  describedBy?: string;
  className?: string;
  placeholder?: string;
  focusOnMount?: boolean;
  focusTarget?: boolean;
  onChange(value: string, mentions: MentionOccurrence[]): void;
}

const InertMentionSource = (_props: EntitySourceProps) => null;

const MentionDecorator = ({
  contentState,
  entityKey,
  children,
}: EntityDecoratorProps) => {
  const data = contentState.getEntity(entityKey).getData() as {
    key: string;
    userId: string;
    label: string;
  };

  return (
    <MentionSpan
      mention={{
        key: data.key,
        userId: data.userId,
        start: 0,
        end: data.label.length,
        label: data.label,
      }}
    >
      {children}
    </MentionSpan>
  );
};

const ENTITY_TYPES = [
  {
    type: 'MENTION',
    source: InertMentionSource,
    decorator: MentionDecorator,
    attributes: ['key', 'userId', 'label'],
  },
];

const editorValuesEqual = (
  left: { value: string; mentions: readonly MentionOccurrence[] },
  right: { value: string; mentions: readonly MentionOccurrence[] },
) =>
  left.value === right.value &&
  JSON.stringify(serializeMentionOccurrences(left.mentions)) ===
    JSON.stringify(serializeMentionOccurrences(right.mentions));

const mergeDescriptionIds = (...values: Array<string | undefined>) =>
  Array.from(
    new Set(
      values
        .flatMap((value) => (value || '').split(/\s+/))
        .filter((value) => value.length > 0),
    ),
  ).join(' ');

export default function MentionEditor({
  id,
  label,
  value,
  mentions,
  mentionedUsers,
  mentionSuggestionsUrl,
  error,
  describedBy,
  className,
  placeholder,
  focusOnMount = false,
  focusTarget = false,
  onChange,
}: MentionEditorProps): React.ReactElement {
  const [editorState, setEditorState] = React.useState(() =>
    createMentionEditorState(value, mentions),
  );
  const [query, setQuery] = React.useState(() =>
    getMentionQueryFromEditorState(editorState),
  );
  const [composing, setComposing] = React.useState(false);
  const [highlightedIndex, setHighlightedIndex] = React.useState(0);
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const draftailRef = React.useRef<DraftailEditor | null>(null);
  const savedSelectionRef = React.useRef<SelectionState>(
    editorState.getSelection(),
  );
  const awaitingCompositionChangeRef = React.useRef(false);
  const mentionsSignature = JSON.stringify(
    serializeMentionOccurrences(mentions),
  );

  React.useLayoutEffect(() => {
    const currentValue = serializeMentionEditorState(editorState);
    if (editorValuesEqual(currentValue, { value, mentions })) return;

    const nextState = createMentionEditorState(value, mentions);
    savedSelectionRef.current = nextState.getSelection();
    setEditorState(nextState);
    setQuery(getMentionQueryFromEditorState(nextState));
  }, [value, mentionsSignature]);

  React.useEffect(() => {
    if (focusOnMount) draftailRef.current?.focus();
  }, [focusOnMount]);

  const suggestions = useMentionSuggestions({
    url: mentionSuggestionsUrl,
    query,
    composing,
  });
  const listboxOpen =
    suggestions.status === 'ready' && suggestions.suggestions.length > 0;
  const listboxId = `${id}-suggestions`;
  const activeSuggestionIndex = listboxOpen
    ? Math.min(highlightedIndex, suggestions.suggestions.length - 1)
    : 0;
  const activeOptionId = listboxOpen
    ? `${id}-suggestion-${activeSuggestionIndex}`
    : undefined;
  const errorId = error === undefined ? undefined : `${id}-error`;
  const ariaDescribedBy = mergeDescriptionIds(describedBy, errorId);

  React.useEffect(() => {
    setHighlightedIndex(0);
  }, [suggestions.status, suggestions.suggestions]);

  React.useLayoutEffect(() => {
    const editable = containerRef.current?.querySelector<HTMLElement>(
      '[contenteditable="true"]',
    );
    if (!editable) return undefined;

    editable.id = id;
    editable.setAttribute('data-focus-target', String(focusTarget));
    editable.setAttribute('aria-autocomplete', 'list');
    editable.setAttribute('aria-haspopup', 'listbox');

    if (listboxOpen) {
      editable.setAttribute('aria-controls', listboxId);
    } else {
      editable.removeAttribute('aria-controls');
    }

    if (activeOptionId === undefined) {
      editable.removeAttribute('aria-activedescendant');
    } else {
      editable.setAttribute('aria-activedescendant', activeOptionId);
    }

    return () => {
      editable.removeAttribute('id');
      editable.removeAttribute('data-focus-target');
      editable.removeAttribute('aria-autocomplete');
      editable.removeAttribute('aria-haspopup');
      editable.removeAttribute('aria-controls');
      editable.removeAttribute('aria-activedescendant');
    };
  }, [activeOptionId, focusTarget, id, listboxId, listboxOpen]);

  const updateEditorState = React.useCallback(
    (nextEditorState: EditorState) => {
      const normalizedState = normalizeMentionEditorState(nextEditorState);
      const previousValue = serializeMentionEditorState(editorState);
      const nextValue = serializeMentionEditorState(normalizedState);

      savedSelectionRef.current = normalizedState.getSelection();
      setEditorState(normalizedState);

      if (composing) {
        setQuery(null);
        awaitingCompositionChangeRef.current = true;
      } else {
        awaitingCompositionChangeRef.current = false;
        setQuery(getMentionQueryFromEditorState(normalizedState));
      }

      if (!editorValuesEqual(previousValue, nextValue)) {
        onChange(
          nextValue.value,
          nextValue.mentions.map((mention) => ({ ...mention })),
        );
      }
    },
    [composing, editorState, onChange],
  );

  const selectSuggestion = React.useCallback(
    (index: number) => {
      if (query === null) return;
      const suggestion = suggestions.suggestions[index];
      if (suggestion === undefined) return;

      const selectedState = EditorState.forceSelection(
        editorState,
        savedSelectionRef.current,
      );
      updateEditorState(
        insertMentionSuggestion(selectedState, query, suggestion),
      );
      suggestions.close();
      draftailRef.current?.focus();
    },
    [editorState, query, suggestions, updateEditorState],
  );

  const onKeyDownCapture = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (
      (event.ctrlKey || event.metaKey) &&
      ['b', 'i', 'u'].includes(event.key.toLowerCase())
    ) {
      event.preventDefault();
      return;
    }

    if (event.key === 'Tab' && suggestions.status !== 'closed') {
      suggestions.close();
      return;
    }

    if (event.key === 'Escape' && suggestions.status !== 'closed') {
      suggestions.close();
      return;
    }

    if (!listboxOpen) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlightedIndex(
        (activeSuggestionIndex + 1) % suggestions.suggestions.length,
      );
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlightedIndex(
        (activeSuggestionIndex - 1 + suggestions.suggestions.length) %
          suggestions.suggestions.length,
      );
    } else if (event.key === 'Enter') {
      event.preventDefault();
      event.stopPropagation();
      selectSuggestion(activeSuggestionIndex);
    }
  };

  let status: string | null = null;
  if (suggestions.status === 'loading') {
    status = gettext('Loading mention suggestions...');
  } else if (suggestions.status === 'empty') {
    status = gettext('No mention suggestions found.');
  } else if (suggestions.status === 'error') {
    status = gettext('Could not load mention suggestions.');
  }

  return (
    <MentionedUsersContext.Provider value={mentionedUsers}>
      <div
        className={['comment__mention-input', className]
          .filter(Boolean)
          .join(' ')}
        onCompositionStart={() => {
          setComposing(true);
          setQuery(null);
          awaitingCompositionChangeRef.current = true;
        }}
        onCompositionEnd={() => {
          setComposing(false);
        }}
        onKeyDownCapture={onKeyDownCapture}
        ref={containerRef}
      >
        <DraftailEditor
          ref={draftailRef}
          editorState={editorState}
          onChange={updateEditorState}
          ariaLabel={label}
          ariaDescribedBy={ariaDescribedBy || null}
          placeholder={placeholder || null}
          enableHorizontalRule={false}
          enableLineBreak={false}
          showUndoControl={false}
          showRedoControl={false}
          stripPastedStyles
          multiline
          spellCheck
          readOnly={false}
          textDirectionality={null}
          blockTypes={[]}
          inlineStyles={[]}
          entityTypes={ENTITY_TYPES}
          decorators={[]}
          controls={[]}
          commands={false}
          plugins={[]}
          topToolbar={null}
          bottomToolbar={null}
          commandToolbar={null}
          maxListNesting={0}
          stateSaveInterval={250}
        />
        {error === undefined ? null : (
          <p className="comment__mention-error" id={errorId} role="alert">
            {error}
          </p>
        )}
        {status === null ? null : (
          <div
            className={`comment__mention-status comment__mention-status--${suggestions.status}`}
            role="status"
          >
            {status}
          </div>
        )}
        {listboxOpen ? (
          <ul
            aria-label={gettext('Mention suggestions')}
            className="comment__mention-suggestions"
            id={listboxId}
            role="listbox"
          >
            {suggestions.suggestions.map((suggestion, index) => {
              const optionId = `${id}-suggestion-${index}`;
              const selected = index === activeSuggestionIndex;
              return (
                <li key={suggestion.id} role="presentation">
                  <button
                    aria-selected={selected}
                    className={`comment__mention-suggestion${
                      selected
                        ? ' comment__mention-suggestion--highlighted'
                        : ''
                    }`}
                    id={optionId}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      selectSuggestion(index);
                    }}
                    role="option"
                    type="button"
                  >
                    <span>{suggestion.label}</span>
                    <span>{suggestion.email}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </MentionedUsersContext.Provider>
  );
}
