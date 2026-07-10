import { mount } from 'enzyme';
import React from 'react';

import MentionText from './index';

const mentions = [
  { key: 'ada-1', userId: '7', start: 0, end: 4, label: '@Ada' },
  { key: 'bea', userId: '8', start: 8, end: 12, label: '@Bea' },
  { key: 'ada-2', userId: '7', start: 17, end: 21, label: '@Ada' },
];

test('renders escaped plain text and repeated saved mention labels without links', () => {
  const wrapper = mount(
    <MentionText
      text="@Ada <b>@Bea</b> @Ada"
      mentions={mentions}
      mentionedUsers={{
        '7': { email: 'ada@example.com' },
        '8': { email: 'bea@example.com' },
      }}
    />,
  );

  expect(wrapper.text()).toBe('@Ada <b>@Bea</b> @Ada');
  expect(wrapper.find('b')).toHaveLength(0);
  expect(wrapper.find('a')).toHaveLength(0);
  expect(wrapper.find('.comment__mention')).toHaveLength(3);
  expect(wrapper.find('.comment__mention').at(0).text()).toBe('@Ada');
  expect(wrapper.find('.comment__mention').at(0).props()).toMatchObject({
    'data-mention-user-id': '7',
    'data-mention-email': 'ada@example.com',
  });
  expect(wrapper.find('.comment__mention').at(1).props()).toMatchObject({
    'data-mention-user-id': '8',
    'data-mention-email': 'bea@example.com',
  });
});

test.each([
  [
    'overlapping ranges',
    [
      { key: 'one', userId: '7', start: 0, end: 4, label: '@Ada' },
      { key: 'two', userId: '8', start: 3, end: 7, label: 'a an' },
    ],
  ],
  [
    'mismatched labels',
    [{ key: 'one', userId: '7', start: 0, end: 4, label: '@Bea' }],
  ],
  [
    'out-of-bounds ranges',
    [{ key: 'one', userId: '7', start: 0, end: 99, label: '@Ada' }],
  ],
])('renders all content as plain text for %s', (_name, malformedMentions) => {
  const wrapper = mount(
    <MentionText
      text="@Ada and @Bea"
      mentions={malformedMentions}
      mentionedUsers={{ '7': { email: 'ada@example.com' } }}
    />,
  );

  expect(wrapper.text()).toBe('@Ada and @Bea');
  expect(wrapper.find('.comment__mention')).toHaveLength(0);
});

test('omits deleted mentioned-user metadata without changing the visible snapshot', () => {
  const wrapper = mount(
    <MentionText text="@Ada" mentions={[mentions[0]]} mentionedUsers={{}} />,
  );

  expect(wrapper.find('.comment__mention').text()).toBe('@Ada');
  expect(wrapper.find('.comment__mention').prop('data-mention-user-id')).toBe(
    '7',
  );
  expect(
    wrapper.find('.comment__mention').prop('data-mention-email'),
  ).toBeUndefined();
});
