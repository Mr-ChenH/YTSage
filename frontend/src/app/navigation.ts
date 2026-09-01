import { Activity, Download, FolderOpen, History, MonitorPlay, Settings2, SlidersHorizontal } from 'lucide-react';

export const navItems = [
  ['workspace', Download, 'navWorkspace'],
  ['tasks', Activity, 'navTasks'],
  ['history', History, 'navHistory'],
  ['files', FolderOpen, 'navFiles'],
  ['player', MonitorPlay, 'navPlayer'],
  ['settings', SlidersHorizontal, 'navSettings'],
  ['system', Settings2, 'navSystem'],
] as const;

export type Page = (typeof navItems)[number][0];
