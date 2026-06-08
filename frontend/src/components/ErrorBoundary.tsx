import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Root error boundary — catches any unhandled render-time errors in the
 * component tree below it and renders a recovery UI instead of crashing
 * the entire application with a blank white screen.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 *
 * A custom ``fallback`` prop can be provided for inline/partial boundaries.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    // In production, forward to your error-tracking service here
    // (e.g. Sentry.captureException(error, { extra: errorInfo })).
    console.error("[ErrorBoundary] Uncaught render error:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ error: null, errorInfo: null });
  };

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="min-h-screen flex items-center justify-center bg-background px-4">
          <div className="max-w-md w-full text-center space-y-6">
            <div className="flex justify-center">
              <div className="p-4 rounded-full bg-destructive/10">
                <AlertTriangle className="h-10 w-10 text-destructive" />
              </div>
            </div>
            <div className="space-y-2">
              <h1 className="text-2xl font-semibold text-foreground">
                Something went wrong
              </h1>
              <p className="text-muted-foreground text-sm">
                An unexpected error occurred. Refreshing the page usually fixes
                this.
              </p>
              {import.meta.env.DEV && (
                <details className="mt-4 text-left">
                  <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                    Error details (dev only)
                  </summary>
                  <pre className="mt-2 text-xs bg-muted p-3 rounded overflow-auto max-h-48 text-left">
                    {this.state.error.toString()}
                    {"\n\n"}
                    {this.state.errorInfo?.componentStack}
                  </pre>
                </details>
              )}
            </div>
            <div className="flex gap-3 justify-center">
              <button
                onClick={this.handleReset}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
              >
                <RefreshCw className="h-4 w-4" />
                Try again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md border border-input bg-background text-sm font-medium hover:bg-accent transition-colors"
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
