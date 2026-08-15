import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CommentCountBadge } from './CommentCountBadge';

/**
 * The badge is the only thing that tells a reviewer, from a run list, that a
 * discussion exists — comments themselves live inside one run's report and are
 * invisible from anywhere else.
 */
describe('CommentCountBadge', () => {
  it('shows the count', () => {
    render(<CommentCountBadge count={3} />);

    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByLabelText('3 review comments')).toBeInTheDocument();
  });

  it('says "comment" in the singular for one', () => {
    render(<CommentCountBadge count={1} />);

    expect(screen.getByLabelText('1 review comment')).toBeInTheDocument();
  });

  it('renders nothing at zero', () => {
    const { container } = render(<CommentCountBadge count={0} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when the field is missing', () => {
    // Runs indexed before comment counts existed come back without the field.
    const { container } = render(<CommentCountBadge count={undefined} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a non-numeric value', () => {
    const { container } = render(<CommentCountBadge count={'oops' as unknown as number} />);

    expect(container).toBeEmptyDOMElement();
  });
});
