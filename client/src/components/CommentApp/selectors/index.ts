import type { State } from '../state';
import type { Comment } from '../state/comments';
import type { MentionOccurrence } from '../utils/mentions';
import { createSelector } from 'reselect';
import { serializeMentionOccurrences } from '../utils/mentions';

export const selectComments = (state: State) => state.comments.comments;
export const selectFocused = (state: State) => state.comments.focusedComment;
export const selectRemoteCommentCount = (state: State) =>
  state.comments.remoteCommentCount;

export function selectCommentsForContentPathFactory(contentpath: string) {
  return createSelector(selectComments, (comments) =>
    [...comments.values()].filter(
      (comment: Comment) =>
        comment.contentpath === contentpath &&
        !(comment.deleted || comment.resolved),
    ),
  );
}

export function selectCommentFactory(localId: number) {
  return createSelector(selectComments, (comments) => {
    const comment = comments.get(localId);
    if (comment !== undefined && (comment.deleted || comment.resolved)) {
      return undefined;
    }
    return comment;
  });
}

export const selectIsDirty = createSelector(
  selectComments,
  selectRemoteCommentCount,
  (comments, remoteCommentCount) => {
    const mentionsChanged = (
      original: readonly MentionOccurrence[],
      current: readonly MentionOccurrence[],
    ) =>
      JSON.stringify(serializeMentionOccurrences(original)) !==
      JSON.stringify(serializeMentionOccurrences(current));

    const readyComments = Array.from(comments.values()).filter(
      // An empty `creating` comment is still an uncommitted editor draft. A
      // canonical value means the comment is already part of the hidden form.
      (comment) => comment.mode !== 'creating' || comment.text.length > 0,
    );
    if (remoteCommentCount !== readyComments.length) {
      return true;
    }
    return Array.from(comments.values()).some((comment) => {
      if (
        comment.deleted ||
        comment.resolved ||
        comment.replies.size !== comment.remoteReplyCount ||
        comment.originalText !== comment.text ||
        mentionsChanged(comment.originalMentions, comment.mentions)
      ) {
        return true;
      }
      return Array.from(comment.replies.values()).some(
        (reply) =>
          reply.deleted ||
          reply.originalText !== reply.text ||
          mentionsChanged(reply.originalMentions, reply.mentions),
      );
    });
  },
);

export const selectCommentCount = (state: State) =>
  [...state.comments.comments.values()].filter(
    (comment: Comment) => !comment.deleted && !comment.resolved,
  ).length;
