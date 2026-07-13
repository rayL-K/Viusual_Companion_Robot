import { render } from "preact";
import "@fontsource-variable/manrope";

import { App } from "./App";
import "./styles.css";

render(<App />, document.getElementById("app")!);
