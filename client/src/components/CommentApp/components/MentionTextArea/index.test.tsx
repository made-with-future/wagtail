import { mount } from 'enzyme';
import React from 'react';
import { act } from 'react-dom/test-utils';

import MentionTextArea from './index';

const flushPromises = () =>
  new Promise((resolve) => {
    setTimeout(resolve, 0);
  });

const setCaret = (element: HTMLElement, offset: number) => {
  const selection = window.getSelection();
  const range = document.createRange();
  const textNode = element.firstChild || element;

  range.setStart(textNode, offset);
  range.collapse(true);
  selection?.removeAllRanges();
  selection?.addRange(range);
};

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

  const editor = wrapper.find('[contentEditable=true]');
  const editorNode = editor.getDOMNode<HTMLElement>();
  setCaret(editorNode, 'Please review @men'.length);

  await act(async () => {
    editor.simulate('input', {
      currentTarget: { textContent: 'Please review @men' },
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

test('highlights stored mentions in the editable comment text', () => {
  const wrapper = mount(
    <MentionTextArea
      value="Please review @mentioned@example.com"
      mentions={[
        {
          id: 2,
          name: 'Mentioned User',
          email: 'mentioned@example.com',
          url: '/admin/users/2/',
        },
      ]}
    />,
  );

  expect(wrapper.find('textarea')).toHaveLength(0);
  expect(wrapper.find('[contentEditable=true]')).toHaveLength(1);
  expect(wrapper.find('.comment__mention').text()).toBe(
    '@mentioned@example.com',
  );
});

test('pastes plain text into the editable comment text', () => {
  const onChange = jest.fn();
  const wrapper = mount(
    <MentionTextArea value="Hello " mentions={[]} onChange={onChange} />,
  );
  const editor = wrapper.find('[contentEditable=true]');
  const editorNode = editor.getDOMNode<HTMLElement>();
  const preventDefault = jest.fn();

  setCaret(editorNode, 'Hello '.length);
  editor.simulate('paste', {
    preventDefault,
    clipboardData: {
      getData: jest.fn((type: string) =>
        type === 'text/plain' ? 'bold text' : '<strong>bold text</strong>',
      ),
    },
  });

  expect(preventDefault).toHaveBeenCalled();
  expect(onChange).toHaveBeenCalledWith('Hello bold text');
});

test('prevents rich text formatting shortcuts', () => {
  const wrapper = mount(<MentionTextArea value="Hello" mentions={[]} />);
  const preventDefault = jest.fn();

  wrapper.find('[contentEditable=true]').simulate('keyDown', {
    ctrlKey: true,
    key: 'b',
    preventDefault,
  });

  expect(preventDefault).toHaveBeenCalled();
});
