import type { MentionQuery, MentionSuggestion } from '../../utils/mentions';
import type {
  UseMentionSuggestionsOptions,
  UseMentionSuggestionsResult,
} from './useMentionSuggestions';
import { ReactWrapper, mount } from 'enzyme';
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

import { useMentionSuggestions } from './useMentionSuggestions';

const ada: MentionSuggestion = {
  id: '1',
  label: 'Ada Lovelace',
  email: 'ada@example.com',
  username: 'ada',
};

const grace: MentionSuggestion = {
  id: '2',
  label: 'Grace Hopper',
  email: '',
};

const adaQuery: MentionQuery = {
  start: 7,
  end: 11,
  query: 'ada',
};

const defaultOptions: UseMentionSuggestionsOptions = {
  url: '/admin/comment-mention-suggestions/',
  query: adaQuery,
  composing: false,
};

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(reason: unknown): void;
}

const deferred = <T,>(): Deferred<T> => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
};

const jsonResponse = (body: unknown, ok = true) =>
  ({
    ok,
    json: jest.fn().mockResolvedValue(body),
  }) as unknown as Response;

const fetchMock = fetch as jest.MockedFunction<typeof fetch>;

interface RenderedHook {
  result(): UseMentionSuggestionsResult;
  rerender(options: UseMentionSuggestionsOptions): void;
  unmount(): void;
}

interface CommitWindowHook {
  result(): UseMentionSuggestionsResult;
  passiveResults(): UseMentionSuggestionsResult[];
  rerenderBeforePassiveEffects(options: UseMentionSuggestionsOptions): void;
  unmount(): void;
}

const mountedHooks: RenderedHook[] = [];
const commitWindowHooks: CommitWindowHook[] = [];

const renderSuggestions = (
  initialOptions: UseMentionSuggestionsOptions,
): RenderedHook => {
  let latestResult!: UseMentionSuggestionsResult;

  const Harness = (options: UseMentionSuggestionsOptions) => {
    const result = useMentionSuggestions(options);

    React.useEffect(() => {
      latestResult = result;
    }, [result]);

    return null;
  };

  let wrapper!: ReactWrapper<UseMentionSuggestionsOptions>;
  let mounted = true;

  act(() => {
    wrapper = mount(<Harness {...initialOptions} />);
  });

  const renderedHook: RenderedHook = {
    result: () => latestResult,
    rerender: (options) => {
      act(() => {
        wrapper.setProps(options);
      });
      wrapper.update();
    },
    unmount: () => {
      if (!mounted) {
        return;
      }

      act(() => {
        wrapper.unmount();
      });
      mounted = false;
    },
  };

  mountedHooks.push(renderedHook);
  return renderedHook;
};

const renderCommitWindowSuggestions = (
  initialOptions: UseMentionSuggestionsOptions,
): CommitWindowHook => {
  const container = document.createElement('div');
  let latestResult!: UseMentionSuggestionsResult;
  const passiveResults: UseMentionSuggestionsResult[] = [];
  let mounted = true;

  const Harness = (options: UseMentionSuggestionsOptions) => {
    const result = useMentionSuggestions(options);

    React.useLayoutEffect(() => {
      latestResult = result;
    });
    React.useEffect(() => {
      passiveResults.push(result);
    });

    return null;
  };

  act(() => {
    ReactDOM.render(<Harness {...initialOptions} />, container);
  });

  const renderedHook: CommitWindowHook = {
    result: () => latestResult,
    passiveResults: () => passiveResults,
    rerenderBeforePassiveEffects: (options) => {
      ReactDOM.render(<Harness {...options} />, container);
    },
    unmount: () => {
      if (!mounted) {
        return;
      }

      act(() => {
        ReactDOM.unmountComponentAtNode(container);
      });
      mounted = false;
    },
  };

  commitWindowHooks.push(renderedHook);
  return renderedHook;
};

const advance = (milliseconds: number) => {
  act(() => {
    jest.advanceTimersByTime(milliseconds);
  });
};

const settle = async (callback: () => void) => {
  await act(async () => {
    callback();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
};

const flushMicrotasks = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

const requestSignal = (call: number) => {
  const options = fetchMock.mock.calls[call][1] as RequestInit;
  return options.signal as AbortSignal;
};

beforeEach(() => {
  jest.useFakeTimers();
  fetchMock.mockReset();
});

afterEach(() => {
  mountedHooks.splice(0).forEach((hook) => hook.unmount());
  commitWindowHooks.splice(0).forEach((hook) => hook.unmount());
  jest.clearAllTimers();
  jest.useRealTimers();
});

test('suppresses requests without a URL or query and while composing', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions({
    ...defaultOptions,
    url: undefined,
  });

  expect(hook.result()).toMatchObject({ status: 'closed', suggestions: [] });
  advance(200);
  expect(fetchMock).not.toHaveBeenCalled();

  hook.rerender({
    ...defaultOptions,
    query: null,
  });
  advance(200);
  expect(hook.result()).toMatchObject({ status: 'closed', suggestions: [] });
  expect(fetchMock).not.toHaveBeenCalled();

  hook.rerender({
    ...defaultOptions,
    composing: true,
  });
  advance(200);
  expect(hook.result()).toMatchObject({ status: 'closed', suggestions: [] });
  expect(fetchMock).not.toHaveBeenCalled();

  hook.rerender(defaultOptions);
  expect(hook.result()).toMatchObject({ status: 'loading', suggestions: [] });
  advance(200);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('waits for the full default 200 millisecond debounce', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  expect(hook.result()).toMatchObject({ status: 'loading', suggestions: [] });
  advance(199);
  expect(fetchMock).not.toHaveBeenCalled();

  advance(1);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('uses the supplied debounce duration', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  renderSuggestions({ ...defaultOptions, debounceMs: 25 });

  advance(24);
  expect(fetchMock).not.toHaveBeenCalled();
  advance(1);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('clears ready results immediately and replaces a changed tuple request', async () => {
  const firstRequest = deferred<Response>();
  const secondRequest = deferred<Response>();
  fetchMock
    .mockImplementationOnce(() => firstRequest.promise)
    .mockImplementationOnce(() => secondRequest.promise);
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  await settle(() => firstRequest.resolve(jsonResponse({ results: [ada] })));
  expect(hook.result()).toMatchObject({
    status: 'ready',
    suggestions: [ada],
  });

  hook.rerender({
    ...defaultOptions,
    query: { ...adaQuery, start: adaQuery.start + 1 },
  });

  expect(hook.result()).toMatchObject({ status: 'loading', suggestions: [] });
  expect(requestSignal(0).aborted).toBe(true);
  advance(199);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  advance(1);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test('clears suggestions in the replacement commit before passive effects', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ results: [ada] }));
  const hook = renderCommitWindowSuggestions(defaultOptions);

  advance(200);
  await settle(() => {});
  expect(hook.result()).toMatchObject({
    status: 'ready',
    suggestions: [ada],
  });
  const previousPassiveResults = hook.passiveResults().length;

  hook.rerenderBeforePassiveEffects({
    ...defaultOptions,
    query: { ...adaQuery, query: 'grace' },
  });

  expect(hook.result()).toMatchObject({ status: 'loading', suggestions: [] });
  expect(hook.passiveResults().slice(previousPassiveResults)[0]).toMatchObject({
    status: 'loading',
    suggestions: [],
  });
});

test('invalidates an old settlement in the replacement commit before passive effects', async () => {
  const request = deferred<Response>();
  fetchMock.mockImplementationOnce(() => request.promise);
  const hook = renderCommitWindowSuggestions(defaultOptions);

  advance(200);
  hook.rerenderBeforePassiveEffects({
    ...defaultOptions,
    query: { ...adaQuery, query: 'grace' },
  });
  const abortedAfterCommit = requestSignal(0).aborted;

  request.resolve(jsonResponse({ results: [ada] }));
  await flushMicrotasks();

  expect(abortedAfterCommit).toBe(true);
  expect(hook.result()).toMatchObject({ status: 'loading', suggestions: [] });
});

test('cancels timers when the query changes or the popup closes', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  advance(100);
  hook.rerender({
    ...defaultOptions,
    query: { ...adaQuery, query: 'grace' },
  });
  advance(100);
  expect(fetchMock).not.toHaveBeenCalled();

  act(() => hook.result().close());
  expect(hook.result()).toMatchObject({ status: 'closed', suggestions: [] });
  advance(200);
  expect(fetchMock).not.toHaveBeenCalled();
});

type HookTransition = (hook: RenderedHook) => void;

const pendingTimerTransitions: Array<[string, HookTransition]> = [
  [
    'composition',
    (hook) => hook.rerender({ ...defaultOptions, composing: true }),
  ],
  [
    'a missing URL',
    (hook) => hook.rerender({ ...defaultOptions, url: undefined }),
  ],
  [
    'a missing query',
    (hook) => hook.rerender({ ...defaultOptions, query: null }),
  ],
  [
    'close',
    (hook) => {
      act(() => hook.result().close());
    },
  ],
  ['unmount', (hook) => hook.unmount()],
];

test.each(pendingTimerTransitions)(
  'cancels a pending timer on %s',
  (_description, transition) => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
    const hook = renderSuggestions(defaultOptions);

    advance(199);
    transition(hook);
    advance(1);

    expect(fetchMock).not.toHaveBeenCalled();
  },
);

test('aborts active requests on every temporary suppression and restarts afterward', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  expect(requestSignal(0).aborted).toBe(false);

  hook.rerender({ ...defaultOptions, composing: true });
  expect(requestSignal(0).aborted).toBe(true);
  expect(hook.result().status).toBe('closed');

  hook.rerender(defaultOptions);
  expect(hook.result().status).toBe('loading');
  advance(200);
  expect(fetchMock).toHaveBeenCalledTimes(2);

  hook.rerender({ ...defaultOptions, url: undefined });
  expect(requestSignal(1).aborted).toBe(true);
  expect(hook.result().status).toBe('closed');

  hook.rerender(defaultOptions);
  advance(200);
  expect(fetchMock).toHaveBeenCalledTimes(3);

  hook.rerender({ ...defaultOptions, query: null });
  expect(requestSignal(2).aborted).toBe(true);
  expect(hook.result().status).toBe('closed');

  hook.rerender(defaultOptions);
  expect(hook.result().status).toBe('loading');
  advance(200);
  expect(fetchMock).toHaveBeenCalledTimes(4);
});

test('aborts the current request on close and unmount', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  act(() => hook.result().close());
  expect(requestSignal(0).aborted).toBe(true);

  hook.rerender({
    ...defaultOptions,
    query: { ...adaQuery, query: 'grace' },
  });
  advance(200);
  hook.unmount();
  expect(requestSignal(1).aborted).toBe(true);
});

test('cancels a pending timer on unmount', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  advance(199);
  hook.unmount();
  advance(1);
  expect(fetchMock).not.toHaveBeenCalled();
});

type StaleSettlement = 'success' | 'error';

const settleStaleRequest = async (
  request: Deferred<Response>,
  settlement: StaleSettlement,
) => {
  await settle(() => {
    if (settlement === 'success') {
      request.resolve(jsonResponse({ results: [ada] }));
    } else {
      request.reject(new Error('stale network failure'));
    }
  });
};

const staleSuppressionTransitions: Array<[string, HookTransition]> = [
  [
    'composition',
    (hook) => hook.rerender({ ...defaultOptions, composing: true }),
  ],
  [
    'a missing URL',
    (hook) => hook.rerender({ ...defaultOptions, url: undefined }),
  ],
  [
    'a missing query',
    (hook) => hook.rerender({ ...defaultOptions, query: null }),
  ],
  [
    'close',
    (hook) => {
      act(() => hook.result().close());
    },
  ],
];

const staleSuppressionCases = staleSuppressionTransitions.flatMap(
  ([description, transition]) =>
    (['success', 'error'] as StaleSettlement[]).map(
      (settlement) =>
        [settlement, description, transition] as [
          StaleSettlement,
          string,
          HookTransition,
        ],
    ),
);

test.each(staleSuppressionCases)(
  'ignores stale %s after %s',
  async (settlement, _description, transition) => {
    const request = deferred<Response>();
    fetchMock.mockImplementationOnce(() => request.promise);
    const hook = renderSuggestions(defaultOptions);

    advance(200);
    transition(hook);
    expect(requestSignal(0).aborted).toBe(true);

    await settleStaleRequest(request, settlement);
    expect(hook.result()).toMatchObject({
      status: 'closed',
      suggestions: [],
    });
  },
);

test.each<StaleSettlement>(['success', 'error'])(
  'invalidates a stale %s settlement on unmount',
  async (settlement) => {
    const consoleError = jest
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);

    try {
      const request = deferred<Response>();
      fetchMock.mockImplementationOnce(() => request.promise);
      const hook = renderSuggestions(defaultOptions);

      advance(200);
      hook.unmount();
      expect(requestSignal(0).aborted).toBe(true);
      await settleStaleRequest(request, settlement);

      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  },
);

test.each<StaleSettlement>(['success', 'error'])(
  'ignores stale %s while the replacement request is debouncing',
  async (settlement) => {
    const firstRequest = deferred<Response>();
    const secondRequest = deferred<Response>();
    fetchMock
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);
    const hook = renderSuggestions(defaultOptions);

    advance(200);
    hook.rerender({
      ...defaultOptions,
      query: { ...adaQuery, query: 'grace' },
    });
    expect(requestSignal(0).aborted).toBe(true);

    await settleStaleRequest(firstRequest, settlement);
    expect(hook.result()).toMatchObject({
      status: 'loading',
      suggestions: [],
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    advance(200);
    await settle(() =>
      secondRequest.resolve(jsonResponse({ results: [grace] })),
    );
    expect(hook.result()).toMatchObject({
      status: 'ready',
      suggestions: [grace],
    });
  },
);

test.each<StaleSettlement>(['success', 'error'])(
  'ignores stale %s after the replacement request is ready',
  async (settlement) => {
    const firstRequest = deferred<Response>();
    const secondRequest = deferred<Response>();
    fetchMock
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);
    const hook = renderSuggestions(defaultOptions);

    advance(200);
    hook.rerender({
      ...defaultOptions,
      query: { ...adaQuery, query: 'grace' },
    });
    advance(200);
    await settle(() =>
      secondRequest.resolve(jsonResponse({ results: [grace] })),
    );
    expect(hook.result()).toMatchObject({
      status: 'ready',
      suggestions: [grace],
    });

    await settleStaleRequest(firstRequest, settlement);
    expect(hook.result()).toMatchObject({
      status: 'ready',
      suggestions: [grace],
    });
  },
);

test('does not restart an active debounce for an equal query object', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  advance(100);
  hook.rerender({ ...defaultOptions, query: { ...adaQuery } });
  advance(99);
  expect(fetchMock).not.toHaveBeenCalled();
  advance(1);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('reports current non-OK and network failures as errors', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({}, false));
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  await settle(() => {});
  expect(hook.result()).toMatchObject({ status: 'error', suggestions: [] });

  const networkFailure = deferred<Response>();
  fetchMock.mockImplementationOnce(() => networkFailure.promise);
  hook.rerender({
    ...defaultOptions,
    query: { ...adaQuery, query: 'grace' },
  });
  advance(200);
  await settle(() => networkFailure.reject(new Error('offline')));
  expect(hook.result()).toMatchObject({ status: 'error', suggestions: [] });
});

test('keeps AbortError silent for a current request', async () => {
  const request = deferred<Response>();
  fetchMock.mockImplementationOnce(() => request.promise);
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  await settle(() => request.reject(new DOMException('Aborted', 'AbortError')));

  expect(hook.result()).toMatchObject({
    status: 'loading',
    suggestions: [],
  });
});

test.each<[keyof MentionQuery, number | string]>([
  ['start', adaQuery.start + 1],
  ['end', adaQuery.end + 1],
  ['query', 'grace'],
])(
  'latches close across equal rerenders and releases when %s changes',
  (field, value) => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
    const hook = renderSuggestions(defaultOptions);

    act(() => hook.result().close());
    hook.rerender({
      ...defaultOptions,
      query: { ...adaQuery },
    });
    expect(hook.result().status).toBe('closed');
    advance(200);
    expect(fetchMock).not.toHaveBeenCalled();

    hook.rerender({ ...defaultOptions, composing: true });
    hook.rerender({ ...defaultOptions, url: undefined });
    hook.rerender({ ...defaultOptions, query: null });
    hook.rerender(defaultOptions);
    expect(hook.result().status).toBe('closed');

    hook.rerender({
      ...defaultOptions,
      query: { ...adaQuery, [field]: value },
    });
    expect(hook.result().status).toBe('loading');
    advance(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  },
);

test('preserves the close latch when close repeats with a temporarily missing query', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  const hook = renderSuggestions(defaultOptions);

  act(() => hook.result().close());
  hook.rerender({ ...defaultOptions, query: null });
  act(() => hook.result().close());
  hook.rerender({ ...defaultOptions, query: { ...adaQuery } });

  expect(hook.result()).toMatchObject({ status: 'closed', suggestions: [] });
  advance(200);
  expect(fetchMock).not.toHaveBeenCalled();
});

test('publishes valid suggestions and treats valid empty results as empty', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ results: [ada, grace] }));
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  await settle(() => {});
  expect(hook.result()).toMatchObject({
    status: 'ready',
    suggestions: [ada, grace],
  });

  fetchMock.mockResolvedValueOnce(jsonResponse({ results: [] }));
  hook.rerender({
    ...defaultOptions,
    query: { ...adaQuery, query: 'nobody' },
  });
  advance(200);
  await settle(() => {});
  expect(hook.result()).toMatchObject({ status: 'empty', suggestions: [] });
});

const validSuggestion = {
  id: '1',
  label: 'Ada Lovelace',
  email: 'ada@example.com',
};

test.each<[string, unknown]>([
  ['null top-level value', null],
  ['array top-level value', []],
  ['missing results', {}],
  ['non-array results', { results: {} }],
  ['null item', { results: [null] }],
  ['array item', { results: [[]] }],
  ['non-string id', { results: [{ ...validSuggestion, id: 1 }] }],
  [
    'missing id',
    { results: [{ label: 'Ada Lovelace', email: 'ada@example.com' }] },
  ],
  ['non-string label', { results: [{ ...validSuggestion, label: null }] }],
  ['missing label', { results: [{ id: '1', email: 'ada@example.com' }] }],
  ['missing email', { results: [{ id: '1', label: 'Ada Lovelace' }] }],
  ['non-string email', { results: [{ ...validSuggestion, email: null }] }],
  [
    'non-string optional username',
    { results: [{ ...validSuggestion, username: null }] },
  ],
  [
    'mixed valid and malformed items',
    { results: [validSuggestion, { ...validSuggestion, id: 2 }] },
  ],
])('rejects a %s atomically', async (_description, body) => {
  fetchMock.mockResolvedValueOnce(jsonResponse(body));
  const hook = renderSuggestions(defaultOptions);

  advance(200);
  await settle(() => {});

  expect(hook.result()).toMatchObject({ status: 'error', suggestions: [] });
});

test('resolves relative URLs, replaces every q value, and preserves other parameters', () => {
  fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
  renderSuggestions({
    ...defaultOptions,
    url: '/suggestions/?tag=first&q=old&tag=second&q=older&flag=1',
    query: { ...adaQuery, query: 'ada + grace' },
  });

  advance(200);

  const requestUrl = new URL(fetchMock.mock.calls[0][0] as string);
  expect(requestUrl.origin).toBe(window.location.origin);
  expect(requestUrl.pathname).toBe('/suggestions/');
  expect(Array.from(requestUrl.searchParams.entries())).toEqual([
    ['tag', 'first'],
    ['q', 'ada + grace'],
    ['tag', 'second'],
    ['flag', '1'],
  ]);
});
