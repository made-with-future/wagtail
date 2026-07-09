import React from 'react';

import { Mention } from '../../state/comments';
import { TextAreaProps } from '../TextArea';

interface MentionTextAreaProps extends Omit<
  TextAreaProps,
  'additionalAttributes'
> {
  mentions: Mention[];
  mentionSuggestionsUrl?: string;
  onMentionsChange?(mentions: Mention[]): void;
  additionalAttributes?: React.HTMLAttributes<HTMLDivElement>;
}

const getMentionQuery = (value: string, cursorPosition: number) => {
  // Only trigger suggestions while the cursor is inside an unfinished @token.
  const valueBeforeCursor = value.slice(0, cursorPosition);
  const match = /(^|\s)@([^\s@]*)$/.exec(valueBeforeCursor);

  if (!match) {
    return null;
  }

  return {
    start: cursorPosition - match[2].length - 1,
    query: match[2],
  };
};

const getCaretTextOffset = (element: HTMLElement | null) => {
  const selection = window.getSelection();
  if (
    !element ||
    !selection ||
    selection.rangeCount === 0 ||
    !selection.anchorNode ||
    !element.contains(selection.anchorNode)
  ) {
    return element?.textContent?.length ?? 0;
  }

  const range = selection.getRangeAt(0).cloneRange();
  range.selectNodeContents(element);
  range.setEnd(selection.anchorNode, selection.anchorOffset);

  return range.toString().length;
};

const setCaretTextOffset = (element: HTMLElement, offset: number) => {
  const selection = window.getSelection();
  if (!selection) return;

  const range = document.createRange();
  let remainingOffset = offset;
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  let currentNode = walker.nextNode();

  while (currentNode) {
    const textLength = currentNode.textContent?.length ?? 0;
    if (remainingOffset <= textLength) {
      range.setStart(currentNode, remainingOffset);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      return;
    }
    remainingOffset -= textLength;
    currentNode = walker.nextNode();
  }

  range.setStart(element, element.childNodes.length);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
};

const getMentionParts = (text: string, mentions: Mention[]) => {
  const parts: Array<{ text: string; mention?: Mention; index: number }> = [];
  let cursor = 0;

  const findNextMention = (startIndex: number) => {
    let nextMention: { mention: Mention; token: string; index: number } | null =
      null;

    for (const mention of mentions) {
      if (mention.email) {
        const token = `@${mention.email}`;
        const index = text.indexOf(token, startIndex);

        if (index >= 0 && (!nextMention || index < nextMention.index)) {
          nextMention = { mention, token, index };
        }
      }
    }

    return nextMention;
  };

  while (cursor < text.length) {
    const nextMention = findNextMention(cursor);

    if (!nextMention) {
      parts.push({ text: text.slice(cursor), index: cursor });
      break;
    }

    if (nextMention.index > cursor) {
      parts.push({
        text: text.slice(cursor, nextMention.index),
        index: cursor,
      });
    }

    parts.push({
      text: nextMention.token,
      mention: nextMention.mention,
      index: nextMention.index,
    });
    cursor = nextMention.index + nextMention.token.length;
  }

  return parts;
};

export default function MentionTextArea({
  value,
  mentions,
  mentionSuggestionsUrl,
  onChange,
  onMentionsChange,
  className,
  placeholder,
  focusOnMount,
  focusTarget = false,
  additionalAttributes = {},
  ...props
}: MentionTextAreaProps): React.ReactElement {
  const [mentionQuery, setMentionQuery] = React.useState<ReturnType<
    typeof getMentionQuery
  > | null>(null);
  const [suggestions, setSuggestions] = React.useState<Mention[]>([]);
  const [highlightedIndex, setHighlightedIndex] = React.useState(0);
  const editorRef = React.useRef<HTMLDivElement | null>(null);
  const pendingCaretOffset = React.useRef<number | null>(null);

  const updateMentionQuery = (nextValue: string, cursorPosition: number) => {
    setMentionQuery(getMentionQuery(nextValue, cursorPosition));
  };

  React.useEffect(() => {
    if (focusOnMount && editorRef.current) {
      editorRef.current.focus();
    }
  }, [focusOnMount]);

  React.useLayoutEffect(() => {
    if (pendingCaretOffset.current !== null && editorRef.current) {
      setCaretTextOffset(editorRef.current, pendingCaretOffset.current);
      pendingCaretOffset.current = null;
    }
  }, [value, mentions]);

  React.useEffect(() => {
    if (!mentionSuggestionsUrl || !mentionQuery || !mentionQuery.query) {
      setSuggestions([]);
      return undefined;
    }

    // Cancel stale suggestion requests as the user keeps typing.
    const controller = new AbortController();
    const url = new URL(mentionSuggestionsUrl, window.location.origin);
    url.searchParams.set('q', mentionQuery.query);

    fetch(url.toString(), { signal: controller.signal })
      .then((response) => response.json())
      .then(({ results }) => {
        setSuggestions(results);
        setHighlightedIndex(0);
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setSuggestions([]);
        }
      });

    return () => {
      controller.abort();
    };
  }, [mentionSuggestionsUrl, mentionQuery?.query]);

  const updateMentionsForText = (nextValue: string) => {
    // If the plain-text @email token is removed, drop the stored mention too.
    onMentionsChange?.(
      mentions.filter((mention) => nextValue.includes(`@${mention.email}`)),
    );
  };

  const onChangeValue = (nextValue: string) => {
    const caretOffset = getCaretTextOffset(editorRef.current);
    pendingCaretOffset.current = caretOffset;
    onChange?.(nextValue);
    updateMentionsForText(nextValue);
    updateMentionQuery(nextValue, caretOffset);
  };

  const selectMention = (mention: Mention) => {
    if (!mentionQuery) return;

    // Insert a readable @email token, but keep the exact user id in state.
    const beforeMention = value.slice(0, mentionQuery.start);
    const caretOffset = getCaretTextOffset(editorRef.current);
    const afterMention = value.slice(caretOffset);
    const nextValue = `${beforeMention}@${mention.email} ${afterMention}`;
    const nextMentions = mentions.some(
      (currentMention) => String(currentMention.id) === String(mention.id),
    )
      ? mentions
      : [...mentions, mention];

    pendingCaretOffset.current = `${beforeMention}@${mention.email} `.length;
    onChange?.(nextValue);
    onMentionsChange?.(nextMentions);
    setMentionQuery(null);
    setSuggestions([]);
  };

  const onInput = (event: React.FormEvent<HTMLDivElement>) => {
    onChangeValue(event.currentTarget.textContent || '');
  };

  const onPaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault();
    const plainText = event.clipboardData.getData('text/plain');
    const caretOffset = getCaretTextOffset(editorRef.current);
    const nextValue = `${value.slice(0, caretOffset)}${plainText}${value.slice(
      caretOffset,
    )}`;
    pendingCaretOffset.current = caretOffset + plainText.length;
    onChange?.(nextValue);
    updateMentionsForText(nextValue);
    updateMentionQuery(nextValue, pendingCaretOffset.current);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    additionalAttributes.onKeyDown?.(event);

    if (
      (event.ctrlKey || event.metaKey) &&
      ['b', 'i', 'u'].includes(event.key.toLowerCase())
    ) {
      event.preventDefault();
      return;
    }

    if (!suggestions.length) {
      return;
    }

    // Keep keyboard navigation inside the typeahead suggestions.
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlightedIndex((highlightedIndex + 1) % suggestions.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlightedIndex(
        (highlightedIndex - 1 + suggestions.length) % suggestions.length,
      );
    } else if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault();
      selectMention(suggestions[highlightedIndex]);
    } else if (event.key === 'Escape') {
      setSuggestions([]);
      setMentionQuery(null);
    }
  };

  const classNames = [
    'comment__mention-editor',
    value ? null : 'comment__mention-editor--empty',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  const mentionParts = getMentionParts(value, mentions);

  return (
    <div className="comment__mention-input">
      <div
        {...props}
        {...additionalAttributes}
        aria-multiline="true"
        className={classNames}
        contentEditable
        data-focus-target={focusTarget}
        data-placeholder={placeholder}
        onDrop={(event) => event.preventDefault()}
        onInput={onInput}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        ref={editorRef}
        role="textbox"
        suppressContentEditableWarning
        tabIndex={0}
      >
        {mentionParts.map((part) =>
          part.mention ? (
            <span
              className="comment__mention"
              data-user-id={String(part.mention.id)}
              key={`${part.mention.id}-${part.index}`}
            >
              {part.text}
            </span>
          ) : (
            part.text
          ),
        )}
      </div>
      {suggestions.length ? (
        <ul className="comment__mention-suggestions">
          {suggestions.map((suggestion, index) => (
            <li key={String(suggestion.id)}>
              <button
                className={`comment__mention-suggestion${
                  index === highlightedIndex
                    ? ' comment__mention-suggestion--highlighted'
                    : ''
                }`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  selectMention(suggestion);
                }}
                type="button"
              >
                <span>{suggestion.email}</span>
                <span>{suggestion.name}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
