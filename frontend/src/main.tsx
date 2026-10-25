import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ToastHost } from "./ui";
import "@fontsource-variable/lexend";
import "@fontsource-variable/fraunces";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");

createRoot(root).render(
  <StrictMode>
    <ToastHost>
      <App />
    </ToastHost>
  </StrictMode>,
);
import "./homeflow.css";
import "./bank-layout.css";

import "./typography.css";
