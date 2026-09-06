import { createFileRoute } from "@tanstack/react-router";
import { StenografApp } from "@/components/stenograf/app";
export const Route = createFileRoute("/")({ component: () => <StenografApp /> });
