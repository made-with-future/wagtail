import type { UseMentionSuggestionsResult } from './useMentionSuggestions';
import type { MentionEditorProps } from './index';
import { ContentBlock, EditorState, Modifier, SelectionState } from 'draft-js';
import { ReactWrapper, mount } from 'enzyme';
import React from 'react';
import { act } from 'react-dom/test-utils';

import { serializeMentionEditorState } from './draftail';
import { useMentionSuggestions } from './useMentionSuggestions';
import MentionEditor from './index';

jest.mock('./useMentionSuggestions', () => ({
  useMentionSuggestions: jest.fn(),
}));

const useSuggestionsMock = useMentionSuggestions as jest.MockedFunction<
  typeof useMentionSuggestions
>;

const ada = {
  id: '7',
  label: '@Ada',
  email: 'ada@example.com',
  username: 'ada',
};
const bea = {
  id: '8',
  label: '@Bea',
  email: 'bea@example.com',
};
const close = jest.fn();

const suggestionState = (
  overrides: Partial<UseMentionSuggestionsResult> = {},
): UseMentionSuggestionsResult => ({
  status: 'closed',
  suggestions: [],
  close,
  ...overrides,
});

const baseProps: MentionEditorProps = {
  id: 'comment-mention-editor-1',
  label: 'Add a comment',
  value: '',
  mentions: [],
  mentionedUsers: {},
  mentionSuggestionsUrl: '/admin/mentions/',
  onChange: jest.fn(),
};

const firstBlock = (state: EditorState) =>
  state.getCurrentContent().getFirstBlock();

const select = (
  block: ContentBlock,
  start: number,
  end = start,
): SelectionState =>
  SelectionState.createEmpty(block.getKey()).merge({
    anchorOffset: start,
    focusOffset: end,
    hasFocus: true,
  }) as SelectionState;

const draftail = (wrapper: ReactWrapper) =>
  wrapper.findWhere((node) => node.name() === 'DraftailEditor').first();

const changeEditor = (wrapper: ReactWrapper, state: EditorState) => {
  act(() => {
    draftail(wrapper).invoke('onChange')(state);
  });
  wrapper.update();
};

const editorState = (wrapper: ReactWrapper) =>
  draftail(wrapper).prop('editorState') as EditorState;

const editableElement = (wrapper: ReactWrapper) =>
  wrapper.getDOMNode().querySelector('[contenteditable="true"]') as HTMLElement;

beforeEach(() => {
  close.mockReset();
  useSuggestionsMock.mockReset();
  useSuggestionsMock.mockReturnValue(suggestionState());
  (baseProps.onChange as jest.Mock).mockReset();
});

afterEach(() => {
  delete (window as any).django;
});

test('renders one accessible multiline contenteditable and explicitly disables rich-text UI', () => {
  const wrapper = mount(
    <MentionEditor
      {...baseProps}
      focusTarget
      describedBy="comment-description-1 shared-description"
      error="Enter a valid mention list."
    />,
  );

  expect(
    wrapper.getDOMNode().querySelectorAll('[contenteditable="true"]'),
  ).toHaveLength(1);
  expect(wrapper.find('textarea')).toHaveLength(0);
  expect(wrapper.find('.Draftail-Toolbar')).toHaveLength(0);
  const editable = editableElement(wrapper);
  expect(editable.id).toBe('comment-mention-editor-1');
  expect(editable.getAttribute('data-focus-target')).toBe('true');
  expect(editable.getAttribute('role')).toBe('combobox');
  expect(editable.getAttribute('aria-autocomplete')).toBe('list');
  expect(editable.getAttribute('aria-expanded')).toBe('false');
  expect(editable.hasAttribute('aria-controls')).toBe(false);
  expect(editable.hasAttribute('aria-activedescendant')).toBe(false);
  expect(draftail(wrapper).props()).toMatchObject({
    ariaLabel: 'Add a comment',
    ariaDescribedBy:
      'comment-description-1 shared-description comment-mention-editor-1-error',
    multiline: true,
    topToolbar: null,
    bottomToolbar: null,
    commandToolbar: null,
    commands: false,
    showUndoControl: false,
    showRedoControl: false,
    blockTypes: [],
    inlineStyles: [],
    controls: [],
  });
  const entityTypes = draftail(wrapper).prop('entityTypes') as Array<{
    source: React.ComponentType;
  }>;
  expect(
    mount(React.createElement(entityTypes[0].source)).isEmptyRender(),
  ).toBe(true);
});

test('keeps selection and focus transitions local without parent callbacks', () => {
  const wrapper = mount(<MentionEditor {...baseProps} value="Hello" />);
  const initial = editorState(wrapper);
  const selected = EditorState.forceSelection(
    initial,
    select(firstBlock(initial), 5),
  );

  changeEditor(wrapper, selected);
  editableElement(wrapper).dispatchEvent(
    new Event('focusin', { bubbles: true }),
  );

  expect(baseProps.onChange).not.toHaveBeenCalled();
  expect(editorState(wrapper).getSelection().getAnchorOffset()).toBe(5);
});

test('notifies only for serialized changes and preserves state for equal Redux echoes', () => {
  const onChange = jest.fn();
  const wrapper = mount(
    <MentionEditor {...baseProps} value="Hello" onChange={onChange} />,
  );
  const initial = editorState(wrapper);
  const block = firstBlock(initial);
  const changedContent = Modifier.insertText(
    initial.getCurrentContent(),
    select(block, 5),
    '!',
  );
  const changed = EditorState.push(
    initial,
    changedContent,
    'insert-characters',
  );

  changeEditor(wrapper, changed);

  expect(onChange).toHaveBeenCalledWith('Hello!', []);
  const localState = editorState(wrapper);
  wrapper.setProps({ value: 'Hello!', mentions: [] });
  wrapper.update();
  expect(editorState(wrapper)).toBe(localState);

  wrapper.setProps({ value: 'External value', mentions: [] });
  wrapper.update();
  expect(editorState(wrapper)).not.toBe(localState);
  expect(serializeMentionEditorState(editorState(wrapper)).value).toBe(
    'External value',
  );
});

test('metadata-only changes rerender mention decoration without rehydrating', () => {
  const mention = {
    key: 'ada',
    userId: '7',
    start: 0,
    end: 4,
    label: '@Ada',
  };
  const wrapper = mount(
    <MentionEditor
      {...baseProps}
      value="@Ada"
      mentions={[mention]}
      mentionedUsers={{ '7': { email: 'old@example.com' } }}
    />,
  );
  const state = editorState(wrapper);
  expect(wrapper.find('.comment__mention').prop('data-mention-email')).toBe(
    'old@example.com',
  );

  wrapper.setProps({
    mentionedUsers: { '7': { email: 'new@example.com' } },
  });
  wrapper.update();

  expect(editorState(wrapper)).toBe(state);
  expect(wrapper.find('.comment__mention').prop('data-mention-email')).toBe(
    'new@example.com',
  );
});

test('bridges popup ownership and active option only while a ready list exists', () => {
  useSuggestionsMock.mockReturnValue(
    suggestionState({ status: 'ready', suggestions: [ada, bea] }),
  );
  const wrapper = mount(<MentionEditor {...baseProps} value="@ad" />);
  const state = editorState(wrapper);
  changeEditor(
    wrapper,
    EditorState.forceSelection(state, select(firstBlock(state), 3)),
  );

  expect(wrapper.find('[role="listbox"]')).toHaveLength(1);
  expect(editableElement(wrapper).getAttribute('aria-expanded')).toBe('true');
  expect(editableElement(wrapper).getAttribute('aria-controls')).toBe(
    'comment-mention-editor-1-suggestions',
  );
  expect(editableElement(wrapper).getAttribute('aria-activedescendant')).toBe(
    'comment-mention-editor-1-suggestion-0',
  );

  useSuggestionsMock.mockReturnValue(suggestionState());
  wrapper.setProps({ mentionedUsers: {} });
  wrapper.update();
  expect(editableElement(wrapper).getAttribute('aria-expanded')).toBe('false');
  expect(editableElement(wrapper).hasAttribute('aria-controls')).toBe(false);
  expect(editableElement(wrapper).hasAttribute('aria-activedescendant')).toBe(
    false,
  );
});

test('ready Enter inserts before Draft, Tab only closes, and ordinary Enter stays multiline', () => {
  useSuggestionsMock.mockReturnValue(
    suggestionState({ status: 'ready', suggestions: [ada] }),
  );
  const onChange = jest.fn();
  const wrapper = mount(
    <MentionEditor {...baseProps} value="@ad" onChange={onChange} />,
  );
  const state = editorState(wrapper);
  changeEditor(
    wrapper,
    EditorState.forceSelection(state, select(firstBlock(state), 3)),
  );
  const capture = wrapper
    .find('.comment__mention-input')
    .prop('onKeyDownCapture') as React.KeyboardEventHandler;
  const enter = {
    key: 'Enter',
    preventDefault: jest.fn(),
    stopPropagation: jest.fn(),
  } as unknown as React.KeyboardEvent;

  act(() => capture(enter));
  wrapper.update();
  expect(enter.preventDefault).toHaveBeenCalled();
  expect(enter.stopPropagation).toHaveBeenCalled();
  expect(onChange).toHaveBeenCalledWith('@Ada ', [
    expect.objectContaining({ userId: '7', label: '@Ada' }),
  ]);

  const tab = {
    key: 'Tab',
    preventDefault: jest.fn(),
    stopPropagation: jest.fn(),
  } as unknown as React.KeyboardEvent;
  act(() => capture(tab));
  expect(close).toHaveBeenCalled();
  expect(tab.preventDefault).not.toHaveBeenCalled();
  expect(tab.stopPropagation).not.toHaveBeenCalled();

  useSuggestionsMock.mockReturnValue(suggestionState());
  wrapper.setProps({ mentionedUsers: {} });
  wrapper.update();
  const closedCapture = wrapper
    .find('.comment__mention-input')
    .prop('onKeyDownCapture') as React.KeyboardEventHandler;
  const ordinaryEnter = {
    key: 'Enter',
    preventDefault: jest.fn(),
    stopPropagation: jest.fn(),
  } as unknown as React.KeyboardEvent;
  act(() => closedCapture(ordinaryEnter));
  expect(ordinaryEnter.preventDefault).not.toHaveBeenCalled();
  expect(ordinaryEnter.stopPropagation).not.toHaveBeenCalled();
});

test.each(['b', 'i', 'u'])('blocks Ctrl/Cmd+%s formatting shortcuts', (key) => {
  const wrapper = mount(<MentionEditor {...baseProps} />);
  const capture = wrapper
    .find('.comment__mention-input')
    .prop('onKeyDownCapture') as React.KeyboardEventHandler;
  const event = {
    key,
    ctrlKey: true,
    metaKey: false,
    preventDefault: jest.fn(),
    stopPropagation: jest.fn(),
  } as unknown as React.KeyboardEvent;

  capture(event);

  expect(event.preventDefault).toHaveBeenCalled();
});

test('arrow navigation wraps, Escape closes, and pointer insertion uses the saved selection', () => {
  useSuggestionsMock.mockReturnValue(
    suggestionState({ status: 'ready', suggestions: [ada, bea] }),
  );
  const onChange = jest.fn();
  const wrapper = mount(
    <MentionEditor {...baseProps} value="@ad tail" onChange={onChange} />,
  );
  const state = editorState(wrapper);
  changeEditor(
    wrapper,
    EditorState.forceSelection(state, select(firstBlock(state), 3)),
  );
  const capture = wrapper
    .find('.comment__mention-input')
    .prop('onKeyDownCapture') as React.KeyboardEventHandler;

  act(() =>
    capture({
      key: 'ArrowUp',
      preventDefault: jest.fn(),
    } as unknown as React.KeyboardEvent),
  );
  wrapper.update();
  expect(editableElement(wrapper).getAttribute('aria-activedescendant')).toBe(
    'comment-mention-editor-1-suggestion-1',
  );

  const pointer = {
    preventDefault: jest.fn(),
  } as unknown as React.MouseEvent;
  act(() => {
    wrapper
      .find('#comment-mention-editor-1-suggestion-1')
      .invoke('onMouseDown')(pointer);
  });
  wrapper.update();
  expect(pointer.preventDefault).toHaveBeenCalled();
  expect(onChange).toHaveBeenCalledWith('@Bea  tail', [
    expect.objectContaining({ userId: '8', label: '@Bea' }),
  ]);

  capture({ key: 'Escape' } as React.KeyboardEvent);
  expect(close).toHaveBeenCalled();
});

test('composition defers query recomputation until the subsequent Draft change', () => {
  const wrapper = mount(<MentionEditor {...baseProps} />);
  const input = wrapper.find('.comment__mention-input');
  act(() => input.invoke('onCompositionStart')?.({} as React.CompositionEvent));
  wrapper.update();

  let state = editorState(wrapper);
  let content = Modifier.insertText(
    state.getCurrentContent(),
    select(firstBlock(state), 0),
    '@ad',
  );
  state = EditorState.push(state, content, 'insert-characters');
  state = EditorState.forceSelection(state, select(firstBlock(state), 3));
  changeEditor(wrapper, state);
  expect(useSuggestionsMock.mock.calls.at(-1)?.[0]).toMatchObject({
    composing: true,
    query: null,
  });

  act(() => input.invoke('onCompositionEnd')?.({} as React.CompositionEvent));
  wrapper.update();
  expect(useSuggestionsMock.mock.calls.at(-1)?.[0]).toMatchObject({
    composing: false,
    query: null,
  });

  content = state.getCurrentContent();
  changeEditor(wrapper, EditorState.set(state, { currentContent: content }));
  expect(useSuggestionsMock.mock.calls.at(-1)?.[0]).toMatchObject({
    composing: false,
    query: { start: 0, end: 3, query: 'ad' },
  });
});

test.each(['loading', 'empty', 'error'] as const)(
  'localizes the %s suggestion status without changing combobox state',
  (status) => {
    const messages = {
      loading: 'Loading mention suggestions...',
      empty: 'No mention suggestions found.',
      error: 'Could not load mention suggestions.',
    };
    const gettext = jest.fn((message: string) => `Translated: ${message}`);
    (window as any).django = { gettext };
    useSuggestionsMock.mockReturnValue(suggestionState({ status }));
    const wrapper = mount(<MentionEditor {...baseProps} value="@ad" />);

    expect(wrapper.find(`.comment__mention-status--${status}`).text()).toBe(
      `Translated: ${messages[status]}`,
    );
    expect(gettext).toHaveBeenCalledWith(messages[status]);
    expect(wrapper.find('[role="listbox"]')).toHaveLength(0);
    expect(editableElement(wrapper).getAttribute('aria-expanded')).toBe(
      'false',
    );
  },
);

test('keeps localized ready results and active-option ARIA aligned', () => {
  const gettext = jest.fn((message: string) => `Translated: ${message}`);
  (window as any).django = { gettext };
  useSuggestionsMock.mockReturnValue(
    suggestionState({ status: 'ready', suggestions: [ada, bea] }),
  );
  const wrapper = mount(<MentionEditor {...baseProps} value="@ad" />);
  const state = editorState(wrapper);
  changeEditor(
    wrapper,
    EditorState.forceSelection(state, select(firstBlock(state), 3)),
  );

  const options = wrapper.find('[role="option"]');
  expect(options).toHaveLength(2);
  expect(options.at(0).text()).toBe('@Adaada@example.com');
  expect(options.at(0).prop('aria-selected')).toBe(true);
  expect(options.at(1).text()).toBe('@Beabea@example.com');
  expect(options.at(1).prop('aria-selected')).toBe(false);
  expect(editableElement(wrapper).getAttribute('aria-activedescendant')).toBe(
    'comment-mention-editor-1-suggestion-0',
  );
  expect(gettext).not.toHaveBeenCalledWith('@Ada');
  expect(gettext).not.toHaveBeenCalledWith('ada@example.com');
});

test('clamps selection and Enter together when ready results shrink', () => {
  const suggestions = [ada, bea];
  useSuggestionsMock.mockReturnValue(
    suggestionState({ status: 'ready', suggestions }),
  );
  const onChange = jest.fn();
  const wrapper = mount(
    <MentionEditor {...baseProps} value="@ad" onChange={onChange} />,
  );
  const state = editorState(wrapper);
  changeEditor(
    wrapper,
    EditorState.forceSelection(state, select(firstBlock(state), 3)),
  );
  const capture = wrapper
    .find('.comment__mention-input')
    .prop('onKeyDownCapture') as React.KeyboardEventHandler;
  act(() =>
    capture({
      key: 'ArrowUp',
      preventDefault: jest.fn(),
    } as unknown as React.KeyboardEvent),
  );
  wrapper.update();
  expect(editableElement(wrapper).getAttribute('aria-activedescendant')).toBe(
    'comment-mention-editor-1-suggestion-1',
  );

  suggestions.splice(1, 1);
  wrapper.setProps({ mentionedUsers: {} });
  wrapper.update();
  expect(editableElement(wrapper).getAttribute('aria-activedescendant')).toBe(
    'comment-mention-editor-1-suggestion-0',
  );
  expect(wrapper.find('[role="option"]').prop('aria-selected')).toBe(true);

  const enter = {
    key: 'Enter',
    preventDefault: jest.fn(),
    stopPropagation: jest.fn(),
  } as unknown as React.KeyboardEvent;
  act(() =>
    (
      wrapper
        .find('.comment__mention-input')
        .prop('onKeyDownCapture') as React.KeyboardEventHandler
    )(enter),
  );
  wrapper.update();
  expect(onChange).toHaveBeenCalledWith('@Ada ', [
    expect.objectContaining({ userId: '7', label: '@Ada' }),
  ]);
});

test('cut and paste Draft states notify once and preserve one-step undo and redo', () => {
  const onChange = jest.fn();
  const wrapper = mount(
    <MentionEditor {...baseProps} value="Hello" onChange={onChange} />,
  );
  const initial = editorState(wrapper);
  const block = firstBlock(initial);
  const pastedContent = Modifier.insertText(
    initial.getCurrentContent(),
    select(block, 5),
    ' pasted',
  );
  const pasted = EditorState.push(initial, pastedContent, 'insert-characters');
  changeEditor(wrapper, pasted);
  expect(onChange).toHaveBeenLastCalledWith('Hello pasted', []);

  changeEditor(wrapper, EditorState.undo(editorState(wrapper)));
  expect(onChange).toHaveBeenLastCalledWith('Hello', []);
  changeEditor(wrapper, EditorState.redo(editorState(wrapper)));
  expect(onChange).toHaveBeenLastCalledWith('Hello pasted', []);

  const current = editorState(wrapper);
  const currentBlock = firstBlock(current);
  const cutContent = Modifier.removeRange(
    current.getCurrentContent(),
    select(currentBlock, 5, 12),
    'forward',
  );
  changeEditor(wrapper, EditorState.push(current, cutContent, 'remove-range'));
  expect(onChange).toHaveBeenLastCalledWith('Hello', []);
});
