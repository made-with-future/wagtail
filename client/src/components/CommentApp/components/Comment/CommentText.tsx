import React from 'react';

import { Mention } from '../../state/comments';

interface CommentTextProps {
  text: string;
  mentions: Mention[];
}

export default function CommentText({
  text,
  mentions,
}: CommentTextProps): React.ReactElement {
  const parts: React.ReactNode[] = [];
  let cursor = 0;

  const findNextMention = (startIndex: number) => {
    // Find the next stored @email token so only known mentions become links.
    let nextMention: {
      mention: Mention;
      token: string;
      index: number;
    } | null = null;

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
      parts.push(text.slice(cursor));
      break;
    }

    if (nextMention.index > cursor) {
      parts.push(text.slice(cursor, nextMention.index));
    }

    parts.push(
      <a
        className="comment__mention"
        data-user-id={String(nextMention.mention.id)}
        href={nextMention.mention.url}
        key={`${nextMention.mention.id}-${nextMention.index}`}
      >
        {nextMention.token}
      </a>,
    );

    cursor = nextMention.index + nextMention.token.length;
  }

  return <p className="comment__text">{parts}</p>;
}
