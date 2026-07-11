import { render } from "preact";

import { App } from "./app/App";
import "./styles/tokens.css";
import "./styles/app.css";

render(<App />, document.getElementById("app")!);
