import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthPrompt } from "./lib/authPrompt";
import { BusToastBridge } from "./lib/busToasts";
import { EventStreamProvider } from "./lib/eventStream";
import { ToastProvider } from "./lib/toast";
import { WatchdogHeartbeat } from "./lib/watchdog";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <EventStreamProvider>
        <ToastProvider>
          <BusToastBridge />
          <WatchdogHeartbeat actor="dashboard" />
          <BrowserRouter>
            <App />
          </BrowserRouter>
          <AuthPrompt />
        </ToastProvider>
      </EventStreamProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
