import type { MentionOccurrence, MentionedUser } from '../../utils/mentions';
import React from 'react';

import { splitTextByMentions } from '../../utils/mentions';

export const MentionedUsersContext = React.createContext<
  Readonly<Record<string, MentionedUser>>
>({});

interface MentionSpanProps {
  mention: MentionOccurrence;
  children: React.ReactNode;
}

export function MentionSpan({
  mention,
  children,
}: MentionSpanProps): React.ReactElement {
  const mentionedUsers = React.useContext(MentionedUsersContext);
  const email = mentionedUsers[mention.userId]?.email;

  return (
    <span
      className="comment__mention"
      data-mention-user-id={mention.userId}
      data-mention-email={email}
    >
      {children}
    </span>
  );
}

export interface CommentTextProps {
  text: string;
  mentions: readonly MentionOccurrence[];
  mentionedUsers: Readonly<Record<string, MentionedUser>>;
}

export default function CommentText({
  text,
  mentions,
  mentionedUsers,
}: CommentTextProps): React.ReactElement {
  const content = splitTextByMentions(text, mentions).map((part) =>
    part.mention ? (
      <MentionSpan key={part.mention.key} mention={part.mention}>
        {part.text}
      </MentionSpan>
    ) : (
      part.text
    ),
  );

  return (
    <MentionedUsersContext.Provider value={mentionedUsers}>
      <p className="comment__text">{content}</p>
    </MentionedUsersContext.Provider>
  );
}
