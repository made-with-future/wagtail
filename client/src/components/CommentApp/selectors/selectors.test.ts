import type { MentionOccurrence } from '../utils/mentions';
import { basicCommentsState } from '../__fixtures__/state';
import * as actions from '../actions/comments';
import { reducer } from '../state';
import {
  INITIAL_STATE as INITIAL_COMMENTS_STATE,
  newComment,
  newCommentReply,
} from '../state/comments';
import { INITIAL_STATE as INITIAL_SETTINGS_STATE } from '../state/settings';

import { selectCommentsForContentPathFactory, selectIsDirty } from './index';

test('Select comments for contentpath', () => {
  // test that the selectCommentsForContentPathFactory can generate selectors for the two
  // contentpaths in basicCommentsState
  const state = {
    comments: basicCommentsState,
    settings: INITIAL_SETTINGS_STATE,
  };
  const testContentPathSelector =
    selectCommentsForContentPathFactory('test_contentpath');
  const testContentPathSelector2 =
    selectCommentsForContentPathFactory('test_contentpath_2');
  const selectedComments = testContentPathSelector(state);
  expect(selectedComments.length).toBe(1);
  expect(selectedComments[0].contentpath).toBe('test_contentpath');
  const otherSelectedComments = testContentPathSelector2(state);
  expect(otherSelectedComments.length).toBe(1);
  expect(otherSelectedComments[0].contentpath).toBe('test_contentpath_2');
});

test('Select is dirty', () => {
  const state = {
    comments: INITIAL_COMMENTS_STATE,
    settings: INITIAL_SETTINGS_STATE,
  };
  const stateWithUnsavedComment = reducer(
    state,
    actions.addComment(
      newComment('test_contentpath', 'test_position', 1, null, null, 0, {
        remoteId: null,
        text: 'my new comment',
      }),
    ),
  );

  expect(selectIsDirty(stateWithUnsavedComment)).toBe(true);

  const stateWithSavedComment = reducer(
    state,
    actions.addComment(
      newComment('test_contentpath', 'test_position', 1, null, null, 0, {
        remoteId: 1,
        text: 'my saved comment',
      }),
    ),
  );

  expect(selectIsDirty(stateWithSavedComment)).toBe(false);

  const stateWithDeletedComment = reducer(
    stateWithSavedComment,
    actions.deleteComment(1),
  );

  expect(selectIsDirty(stateWithDeletedComment)).toBe(true);

  const stateWithResolvedComment = reducer(
    stateWithSavedComment,
    actions.updateComment(1, { resolved: true }),
  );

  expect(selectIsDirty(stateWithResolvedComment)).toBe(true);

  const stateWithEditedComment = reducer(
    stateWithSavedComment,
    actions.updateComment(1, { text: 'edited_text' }),
  );

  expect(selectIsDirty(stateWithEditedComment)).toBe(true);

  const stateWithEditedMentions = reducer(
    stateWithSavedComment,
    actions.updateComment(1, {
      mentions: [
        {
          key: 'mention-1',
          userId: '2',
          start: 0,
          end: 4,
          label: '@Ada',
        },
      ],
    }),
  );

  expect(selectIsDirty(stateWithEditedMentions)).toBe(true);

  const stateWithUnsavedReply = reducer(
    stateWithSavedComment,
    actions.addReply(
      1,
      newCommentReply(2, null, 0, {
        remoteId: null,
        text: 'new reply',
      }),
    ),
  );

  expect(selectIsDirty(stateWithUnsavedReply)).toBe(true);

  const stateWithSavedReply = reducer(
    stateWithSavedComment,
    actions.addReply(
      1,
      newCommentReply(2, null, 0, {
        remoteId: 2,
        text: 'new saved reply',
      }),
    ),
  );

  expect(selectIsDirty(stateWithSavedReply)).toBe(false);

  const stateWithDeletedReply = reducer(
    stateWithSavedReply,
    actions.deleteReply(1, 2),
  );

  expect(selectIsDirty(stateWithDeletedReply)).toBe(true);

  const stateWithEditedReply = reducer(
    stateWithSavedReply,
    actions.updateReply(1, 2, { text: 'edited_text' }),
  );

  expect(selectIsDirty(stateWithEditedReply)).toBe(true);
});

const adaMention: MentionOccurrence = {
  key: 'mention-ada',
  userId: '7',
  start: 6,
  end: 10,
  label: '@Ada',
};

const savedCommentState = (mentions: MentionOccurrence[] = [adaMention]) => {
  const state = {
    comments: INITIAL_COMMENTS_STATE,
    settings: INITIAL_SETTINGS_STATE,
  };
  return reducer(
    state,
    actions.addComment(
      newComment('path', '', 1, null, null, 0, {
        remoteId: 1,
        text: 'Hello @Ada',
        mentions,
      }),
    ),
  );
};

test.each([
  ['key', { ...adaMention, key: 'different-key' }],
  ['user', { ...adaMention, userId: '8' }],
  ['start', { ...adaMention, start: 5 }],
  ['end', { ...adaMention, end: 11 }],
  ['label', { ...adaMention, label: '@Grace' }],
])('mention %s changes make comment state dirty', (_field, changedMention) => {
  const changed = reducer(
    savedCommentState(),
    actions.updateComment(1, { mentions: [changedMention] }),
  );

  expect(selectIsDirty(changed)).toBe(true);
});

test('mention additions, removals, moves, and exact reverts drive dirty state', () => {
  const state = savedCommentState();
  const graceMention: MentionOccurrence = {
    key: 'mention-grace',
    userId: '8',
    start: 15,
    end: 21,
    label: '@Grace',
  };

  expect(
    selectIsDirty(reducer(state, actions.updateComment(1, { mentions: [] }))),
  ).toBe(true);
  expect(
    selectIsDirty(
      reducer(
        state,
        actions.updateComment(1, {
          mentions: [adaMention, graceMention],
        }),
      ),
    ),
  ).toBe(true);
  expect(
    selectIsDirty(
      reducer(
        state,
        actions.updateComment(1, {
          mentions: [{ ...adaMention, start: 12, end: 16 }],
        }),
      ),
    ),
  ).toBe(true);

  const reverted = reducer(
    reducer(state, actions.updateComment(1, { mentions: [graceMention] })),
    actions.updateComment(1, { mentions: [{ ...adaMention }] }),
  );
  expect(selectIsDirty(reverted)).toBe(false);
});

test('reply occurrence changes make state dirty and exact reverts are clean', () => {
  const base = savedCommentState([]);
  const withReply = reducer(
    base,
    actions.addReply(
      1,
      newCommentReply(2, null, 0, {
        remoteId: 2,
        text: 'Hello @Ada',
        mentions: [adaMention],
      }),
    ),
  );
  const changed = reducer(
    withReply,
    actions.updateReply(1, 2, {
      mentions: [{ ...adaMention, key: 'changed' }],
    }),
  );
  const reverted = reducer(
    changed,
    actions.updateReply(1, 2, { mentions: [{ ...adaMention }] }),
  );

  expect(selectIsDirty(changed)).toBe(true);
  expect(selectIsDirty(reverted)).toBe(false);
});

test('message errors and mentioned-user metadata do not make content dirty', () => {
  const state = savedCommentState();
  const withError = reducer(
    state,
    actions.updateComment(1, {
      mentionError: 'Enter a valid mention list.',
    }),
  );

  expect(selectIsDirty(withError)).toBe(false);
  expect(
    selectIsDirty({
      ...withError,
      settings: {
        ...withError.settings,
        mentionedUsers: { '7': { email: 'new@example.com' } },
      },
    }),
  ).toBe(false);
});
