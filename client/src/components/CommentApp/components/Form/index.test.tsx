import { mount } from 'enzyme';
import React from 'react';

import { basicCommentsState } from '../../__fixtures__/state';

import { CommentFormComponent } from './index';

test('outputs mentioned user IDs as JSON', () => {
  const comment = basicCommentsState.comments.get(1);
  expect(comment).toBeDefined();

  if (!comment) return;

  const wrapper = mount(
    <CommentFormComponent comment={comment} formNumber={0} prefix="comments" />,
  );

  expect(wrapper.find('input[name="comments-0-mentions"]').prop('value')).toBe(
    JSON.stringify(['2']),
  );
});
