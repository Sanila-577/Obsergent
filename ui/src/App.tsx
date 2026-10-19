import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { About } from "./pages/About";
import { Compare } from "./pages/Compare";
import { Conversations } from "./pages/Conversations";
import { Findings } from "./pages/Findings";
import { Gateway } from "./pages/Gateway";
import { Overview } from "./pages/Overview";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { Mcps } from "./pages/Mcps";
import { Models } from "./pages/Models";
import { Spending } from "./pages/Spending";
import { SessionDetail, Sessions } from "./pages/Sessions";
import { Skeleton } from "./components/ui";

// The graph pages pull in a graph library that is only needed there: load them on demand.
const Agents = lazy(() => import("./pages/Agents").then((m) => ({ default: m.Agents })));
const MapPage = lazy(() => import("./pages/MapPage").then((m) => ({ default: m.MapPage })));

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="conversations" element={<Conversations />} />
        <Route path="agents" element={<Suspense fallback={<Skeleton lines={4} />}><Agents /></Suspense>} />
        <Route path="mcps" element={<Mcps />} />
        <Route path="models" element={<Models />} />
        <Route path="runs" element={<Runs />} />
        <Route path="activity" element={<Navigate to="/runs" replace />} />
        <Route path="runs/:id" element={<RunDetail />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="sessions/:id" element={<SessionDetail />} />
        <Route path="servers" element={<Navigate to="/mcps" replace />} />
        <Route path="spending" element={<Spending />} />
        <Route path="findings" element={<Findings />} />
        <Route path="gateway" element={<Gateway />} />
        <Route path="map" element={<Suspense fallback={<Skeleton lines={4} />}><MapPage /></Suspense>} />
        <Route path="compare" element={<Compare />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<div className="empty"><h3>Page not found</h3></div>} />
      </Route>
    </Routes>
  );
}
