import type { MentionQuery, MentionSuggestion } from '../../utils/mentions';
import { useCallback, useLayoutEffect, useRef, useState } from 'react';

export type MentionSuggestionStatus =
  | 'closed'
  | 'loading'
  | 'ready'
  | 'empty'
  | 'error';

export interface UseMentionSuggestionsOptions {
  url?: string;
  query: MentionQuery | null;
  composing: boolean;
  debounceMs?: number;
}

export interface UseMentionSuggestionsResult {
  status: MentionSuggestionStatus;
  suggestions: MentionSuggestion[];
  close(): void;
}

interface SuggestionState {
  status: MentionSuggestionStatus;
  suggestions: MentionSuggestion[];
  identity: TransitionIdentity;
  closedQuery: MentionQuery | null;
}

interface TransitionIdentity {
  url?: string;
  queryStart: number | null;
  queryEnd: number | null;
  queryText: string | null;
  composing: boolean;
  debounceMs: number;
}

interface ActiveRequest {
  timer: number | null;
  controller: AbortController;
}

const sameQuery = (left: MentionQuery | null, right: MentionQuery | null) =>
  left !== null &&
  right !== null &&
  left.start === right.start &&
  left.end === right.end &&
  left.query === right.query;

const sameIdentity = (left: TransitionIdentity, right: TransitionIdentity) =>
  left.url === right.url &&
  left.queryStart === right.queryStart &&
  left.queryEnd === right.queryEnd &&
  left.queryText === right.queryText &&
  left.composing === right.composing &&
  left.debounceMs === right.debounceMs;

const makeIdentity = (
  url: string | undefined,
  queryStart: number | null,
  queryEnd: number | null,
  queryText: string | null,
  composing: boolean,
  debounceMs: number,
): TransitionIdentity => ({
  url,
  queryStart,
  queryEnd,
  queryText,
  composing,
  debounceMs,
});

const makeQuery = (
  start: number | null,
  end: number | null,
  query: string | null,
): MentionQuery | null =>
  start === null || end === null || query === null
    ? null
    : { start, end, query };

const copyQuery = (query: MentionQuery | null): MentionQuery | null =>
  query === null ? null : { ...query };

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const validateResponse = (value: unknown): MentionSuggestion[] | null => {
  if (!isObject(value) || !Array.isArray(value.results)) {
    return null;
  }

  const suggestions: MentionSuggestion[] = [];

  for (const item of value.results) {
    if (
      !isObject(item) ||
      typeof item.id !== 'string' ||
      typeof item.label !== 'string' ||
      typeof item.email !== 'string' ||
      (item.username !== undefined && typeof item.username !== 'string')
    ) {
      return null;
    }

    suggestions.push({
      id: item.id,
      label: item.label,
      email: item.email,
      ...(item.username === undefined ? {} : { username: item.username }),
    });
  }

  return suggestions;
};

const isAbortError = (error: unknown) =>
  isObject(error) && error.name === 'AbortError';

export const useMentionSuggestions = ({
  url,
  query,
  composing,
  debounceMs = 200,
}: UseMentionSuggestionsOptions): UseMentionSuggestionsResult => {
  const queryStart = query === null ? null : query.start;
  const queryEnd = query === null ? null : query.end;
  const queryText = query === null ? null : query.query;
  const currentQuery = makeQuery(queryStart, queryEnd, queryText);
  const currentIdentity = makeIdentity(
    url,
    queryStart,
    queryEnd,
    queryText,
    composing,
    debounceMs,
  );
  const [state, setState] = useState<SuggestionState>(() => ({
    status: !url || currentQuery === null || composing ? 'closed' : 'loading',
    suggestions: [],
    identity: currentIdentity,
    closedQuery: null,
  }));
  const generationRef = useRef(0);
  const activeRequestRef = useRef<ActiveRequest | null>(null);
  const closedQueryRef = useRef<MentionQuery | null>(null);

  const invalidateAndCancel = useCallback(() => {
    generationRef.current += 1;

    const activeRequest = activeRequestRef.current;
    activeRequestRef.current = null;

    if (activeRequest === null) {
      return;
    }

    if (activeRequest.timer !== null) {
      window.clearTimeout(activeRequest.timer);
    }
    activeRequest.controller.abort();
  }, []);

  const close = useCallback(() => {
    const nextQuery = makeQuery(queryStart, queryEnd, queryText);
    if (nextQuery !== null) {
      closedQueryRef.current = nextQuery;
    }

    const closedQuery = copyQuery(closedQueryRef.current);
    invalidateAndCancel();
    setState({
      status: 'closed',
      suggestions: [],
      identity: makeIdentity(
        url,
        queryStart,
        queryEnd,
        queryText,
        composing,
        debounceMs,
      ),
      closedQuery,
    });
  }, [
    composing,
    debounceMs,
    invalidateAndCancel,
    queryEnd,
    queryStart,
    queryText,
    url,
  ]);

  useLayoutEffect(() => {
    invalidateAndCancel();

    const effectQuery = makeQuery(queryStart, queryEnd, queryText);
    const effectIdentity = makeIdentity(
      url,
      queryStart,
      queryEnd,
      queryText,
      composing,
      debounceMs,
    );

    if (
      closedQueryRef.current !== null &&
      effectQuery !== null &&
      !sameQuery(closedQueryRef.current, effectQuery)
    ) {
      closedQueryRef.current = null;
    }

    if (
      !url ||
      effectQuery === null ||
      composing ||
      sameQuery(closedQueryRef.current, effectQuery)
    ) {
      setState({
        status: 'closed',
        suggestions: [],
        identity: effectIdentity,
        closedQuery: copyQuery(closedQueryRef.current),
      });
      return invalidateAndCancel;
    }

    const generation = generationRef.current + 1;
    generationRef.current = generation;

    const activeRequest: ActiveRequest = {
      timer: null,
      controller: new AbortController(),
    };
    activeRequestRef.current = activeRequest;
    setState({
      status: 'loading',
      suggestions: [],
      identity: effectIdentity,
      closedQuery: null,
    });

    activeRequest.timer = window.setTimeout(async () => {
      activeRequest.timer = null;

      if (generationRef.current !== generation) {
        return;
      }

      try {
        const requestUrl = new URL(url, window.location.origin);
        requestUrl.searchParams.set('q', effectQuery.query);

        const response = await fetch(requestUrl.toString(), {
          signal: activeRequest.controller.signal,
        });
        if (!response.ok) {
          throw new Error('Mention suggestions request failed');
        }

        const suggestions = validateResponse(await response.json());
        if (suggestions === null) {
          throw new Error('Invalid mention suggestions response');
        }

        if (generationRef.current !== generation) {
          return;
        }

        setState({
          status: suggestions.length === 0 ? 'empty' : 'ready',
          suggestions,
          identity: effectIdentity,
          closedQuery: null,
        });
      } catch (error) {
        if (isAbortError(error) || generationRef.current !== generation) {
          return;
        }

        setState({
          status: 'error',
          suggestions: [],
          identity: effectIdentity,
          closedQuery: null,
        });
      }
    }, debounceMs);

    return invalidateAndCancel;
  }, [
    composing,
    debounceMs,
    invalidateAndCancel,
    queryEnd,
    queryStart,
    queryText,
    url,
  ]);

  if (sameIdentity(state.identity, currentIdentity)) {
    return { status: state.status, suggestions: state.suggestions, close };
  }

  if (
    !url ||
    currentQuery === null ||
    composing ||
    sameQuery(state.closedQuery, currentQuery)
  ) {
    return { status: 'closed', suggestions: [], close };
  }

  return { status: 'loading', suggestions: [], close };
};
