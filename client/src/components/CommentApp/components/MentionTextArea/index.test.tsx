import { mount } from 'enzyme';
import React from 'react';
import { act } from 'react-dom/test-utils';

import MentionTextArea from './index';

const flushPromises = () =>
  new Promise((resolve) => {
    setTimeout(resolve, 0);
  });

test('inserts selected mention suggestion', async () => {
  const onChange = jest.fn();
  const onMentionsChange = jest.fn();
  const mentionedUser = {
    id: 2,
    name: 'Mentioned User',
    email: 'mentioned@example.com',
    url: '/admin/users/2/',
  };

  (fetch as any).mockResponseSuccessJSON(
    JSON.stringify({ results: [mentionedUser] }),
  );

  const wrapper = mount(
    <MentionTextArea
      value="Please review @men"
      mentions={[]}
      mentionSuggestionsUrl="/admin/pages/1/edit/comment-mention-suggestions/"
      onChange={onChange}
      onMentionsChange={onMentionsChange}
    />,
  );

  const textarea = wrapper.find('textarea');
  const textareaNode = textarea.getDOMNode<HTMLTextAreaElement>();
  textareaNode.selectionStart = 'Please review @men'.length;

  await act(async () => {
    textarea.simulate('change', {
      target: { value: 'Please review @men' },
    });

    await flushPromises();
    await flushPromises();
  });
  wrapper.update();

  act(() => {
    wrapper.find('button.comment__mention-suggestion').simulate('mouseDown', {
      preventDefault: jest.fn(),
    });
  });

  expect(onChange).toHaveBeenCalledWith(
    'Please review @mentioned@example.com ',
  );
  expect(onMentionsChange).toHaveBeenCalledWith([mentionedUser]);
});
