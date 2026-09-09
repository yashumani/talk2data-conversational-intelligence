import { createRoot } from "react-dom/client";
import { InternalApp } from "./InternalApp";
import "../styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Workspace root is missing.");
createRoot(root).render(<InternalApp />);
