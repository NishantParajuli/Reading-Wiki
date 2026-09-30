import React from "react";
import ReactDOM from "react-dom/client";

/* Self-hosted variable fonts (latin subsets load on demand via unicode-range).
   Fraunces — display; Geist — interface; Literata — reading; Atkinson
   Hyperlegible Next — the high-legibility reading option; Geist Mono — figures. */
import "@fontsource-variable/fraunces/full.css";
import "@fontsource-variable/fraunces/opsz-italic.css";
import "@fontsource-variable/geist/wght.css";
import "@fontsource-variable/geist-mono/wght.css";
import "@fontsource-variable/literata/opsz.css";
import "@fontsource-variable/literata/opsz-italic.css";
import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/ambient.css";
import "./styles/components.css";
import "./styles/shell.css";
import "./styles/transitions.css";
import "./styles/surfaces/home.css";
import "./styles/surfaces/library.css";
import "./styles/surfaces/novel.css";
import "./styles/surfaces/codex.css";
import "./styles/surfaces/jobs.css";
import "./styles/surfaces/import.css";
import "./styles/surfaces/account.css";
import "./styles/surfaces/admin.css";
import "./styles/surfaces/auth.css";
import "./styles/reader.css";

import { Root } from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
