import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { About } from "./pages/About";
import { Compare } from "./pages/Compare";
import { Findings } from "./pages/Findings";
import { Gateway } from "./pages/Gateway";
import { Overview } from "./pages/Overview";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { Servers } from "./pages/Servers";
import { SessionDetail, Sessions } from "./pages/Sessions";
import { Skeleton } from "./components/ui";

// The map pulls in a graph library that is only needed on that page: load it on demand.
const MapPage = lazy(() => import("./pages/MapPage").then((m) => ({ default: m.MapPage })));

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:id" element={<RunDetail />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="sessions/:id" element={<SessionDetail />} />
        <Route path="servers" element={<Servers />} />
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
