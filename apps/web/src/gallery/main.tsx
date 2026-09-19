import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { GalleryApp } from "./GalleryApp";

const root = document.getElementById("root");
if (!root) throw new Error("Gallery root is missing");
createRoot(root).render(<StrictMode><GalleryApp /></StrictMode>);
