import { shallow } from 'enzyme';
import React from 'react';

import CommentText from './CommentText';

test('renders comment mentions as user links', () => {
  const wrapper = shallow(
    <CommentText
      text="Please check this @mentioned@example.com"
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

  const link = wrapper.find('a.comment__mention');
  expect(link.prop('href')).toBe('/admin/users/2/');
  expect(link.prop('data-user-id')).toBe('2');
  expect(link.text()).toBe('@mentioned@example.com');
});
