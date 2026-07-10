require('./comments');

describe('comments', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('exposes module as global', () => {
    expect(window.comments).toBeDefined();
  });

  it('rebases comment state from autosave success data', () => {
    const updateData = jest
      .spyOn(window.comments.commentApp, 'updateData')
      .mockImplementation(() => {});
    const comments = { comments: [] };

    document.dispatchEvent(
      new CustomEvent('w-autosave:success', {
        detail: { data: { comments } },
      }),
    );

    expect(updateData).toHaveBeenCalledWith(comments);
  });

  it('captures stable comment formset positions before autosave submission', () => {
    const captureSubmittedPositions = jest
      .spyOn(window.comments.commentApp, 'captureSubmittedPositions')
      .mockImplementation(() => {});
    const form = document.createElement('form');
    document.body.appendChild(form);

    form.dispatchEvent(
      new CustomEvent('w-autosave:save', {
        bubbles: true,
        detail: { formData: new FormData(form) },
      }),
    );

    expect(captureSubmittedPositions).toHaveBeenCalledTimes(1);
    form.remove();
  });

  it('hydrates rejected comment state only when autosave error data contains it', () => {
    const hydrateRejectedData = jest
      .spyOn(window.comments.commentApp, 'hydrateRejectedData')
      .mockImplementation(() => {});
    const comments = { comments: [] };

    document.dispatchEvent(
      new CustomEvent('w-autosave:error', {
        detail: { response: { comments } },
      }),
    );

    expect(hydrateRejectedData).toHaveBeenCalledWith(comments);
  });

  it('does not mutate comment state for autosave errors without comment data', () => {
    const updateData = jest
      .spyOn(window.comments.commentApp, 'updateData')
      .mockImplementation(() => {});
    const hydrateRejectedData = jest
      .spyOn(window.comments.commentApp, 'hydrateRejectedData')
      .mockImplementation(() => {});

    document.dispatchEvent(
      new CustomEvent('w-autosave:error', {
        detail: { response: { errors: ['Page title is required'] } },
      }),
    );

    expect(updateData).not.toHaveBeenCalled();
    expect(hydrateRejectedData).not.toHaveBeenCalled();
  });
});
