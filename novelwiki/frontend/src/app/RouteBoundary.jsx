/* Suspense + error boundary for lazily loaded screens. A screen that fails to
   load or render shows a calm recovery card instead of a blank page; a chunk
   that vanished after a deploy offers a reload into the new version. */
import React, { Suspense } from "react";
import { Icon } from "../components/Icon.jsx";

function ScreenLoading() {
  return (
    <div className="screen-loading" role="status" aria-label="Loading">
      <span className="screen-loading-orb" aria-hidden="true" />
    </div>
  );
}

class Boundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const chunk = /dynamically imported module|Importing a module script failed|Failed to fetch|ChunkLoadError|error loading/i.test(String(error && error.message));
    return (
      <div className="page">
        <div className="empty-state screen-error" role="alert">
          <div className="es-icon"><Icon name={chunk ? "refresh" : "alert"} size={26} /></div>
          <b>{chunk ? "A new version of Tideglass is ready" : "This page couldn't open"}</b>
          <p>{chunk ? "Reload to pick up the latest version. Your reading progress is saved." : "Something went wrong while showing this page. Your books and progress are safe."}</p>
          <div className="es-actions">
            <button className="btn btn-primary" onClick={() => window.location.reload()}><Icon name="refresh" size={16} /> Reload</button>
            {!chunk && <button className="btn btn-ghost" onClick={() => this.setState({ error: null })}>Try again</button>}
          </div>
        </div>
      </div>
    );
  }
}

export function RouteBoundary({ children, resetKey }) {
  return (
    <Boundary resetKey={resetKey}>
      <Suspense fallback={<ScreenLoading />}>{children}</Suspense>
    </Boundary>
  );
}
