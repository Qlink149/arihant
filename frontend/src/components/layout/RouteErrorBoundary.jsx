import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../ui/button';

export class RouteErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('RouteErrorBoundary caught:', error, info);
  }

  render() {
    if (this.state.error) {
      return <this.props.fallback error={this.state.error} reset={() => this.setState({ error: null })} />;
    }
    return this.props.children;
  }
}

export function LeadPageErrorFallback({ error, reset }) {
  const navigate = useNavigate();
  const message = error?.message || 'Something went wrong loading this lead.';

  return (
    <div className="text-center py-12 px-4 max-w-lg mx-auto">
      <p className="text-crm-fg font-medium mb-2">Unable to load lead profile</p>
      <p className="text-crm-fg-secondary text-sm mb-6 break-words">{message}</p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button onClick={reset} variant="outline" className="border-crm-border">
          Try again
        </Button>
        <Button onClick={() => navigate('/virtual-customer')} className="bg-[#C5A059] text-black">
          Back to Virtual Customer
        </Button>
      </div>
    </div>
  );
}
