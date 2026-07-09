import React from 'react';

import { Mention } from '../../state/comments';
import TextArea, { TextAreaProps } from '../TextArea';

interface MentionTextAreaProps extends TextAreaProps {
  mentions: Mention[];
  mentionSuggestionsUrl?: string;
  onMentionsChange?(mentions: Mention[]): void;
}

const getMentionQuery = (value: string, cursorPosition: number) => {
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

export default function MentionTextArea({
  value,
  mentions,
  mentionSuggestionsUrl,
  onChange,
  onMentionsChange,
  additionalAttributes = {},
  ...props
}: MentionTextAreaProps): React.ReactElement {
  const textAreaRef = React.useRef<HTMLTextAreaElement | null>(null);
  const [mentionQuery, setMentionQuery] = React.useState<ReturnType<
    typeof getMentionQuery
  > | null>(null);
  const [suggestions, setSuggestions] = React.useState<Mention[]>([]);
  const [highlightedIndex, setHighlightedIndex] = React.useState(0);

  const updateMentionQuery = (nextValue: string) => {
    const cursorPosition =
      textAreaRef.current?.selectionStart ?? nextValue.length;
    setMentionQuery(getMentionQuery(nextValue, cursorPosition));
  };

  React.useEffect(() => {
    if (!mentionSuggestionsUrl || !mentionQuery || !mentionQuery.query) {
      setSuggestions([]);
      return undefined;
    }

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
    onMentionsChange?.(
      mentions.filter((mention) => nextValue.includes(`@${mention.email}`)),
    );
  };

  const onChangeValue = (nextValue: string) => {
    onChange?.(nextValue);
    updateMentionsForText(nextValue);
    updateMentionQuery(nextValue);
  };

  const selectMention = (mention: Mention) => {
    if (!mentionQuery) return;

    const beforeMention = value.slice(0, mentionQuery.start);
    const afterMention = value.slice(
      textAreaRef.current?.selectionStart ?? value.length,
    );
    const nextValue = `${beforeMention}@${mention.email} ${afterMention}`;
    const nextMentions = mentions.some(
      (currentMention) => String(currentMention.id) === String(mention.id),
    )
      ? mentions
      : [...mentions, mention];

    onChange?.(nextValue);
    onMentionsChange?.(nextMentions);
    setMentionQuery(null);
    setSuggestions([]);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    additionalAttributes.onKeyDown?.(event);

    if (!suggestions.length) {
      return;
    }

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

  return (
    <div className="comment__mention-input">
      <TextArea
        {...props}
        ref={textAreaRef}
        value={value}
        onChange={onChangeValue}
        additionalAttributes={{
          ...additionalAttributes,
          onKeyDown,
        }}
      />
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
