import { Activity, Binoculars, Download, FolderOpen, History, MonitorPlay, Settings2, SlidersHorizontal, Users } from 'lucide-react';

export const navItems = [
  ['workspace', Download, 'navWorkspace'],
  ['tasks', Activity, 'navTasks'],
  ['monitors', Binoculars, 'navMonitors'],
  ['history', History, 'navHistory'],
  ['files', FolderOpen, 'navFiles'],
  ['player', MonitorPlay, 'navPlayer'],
  ['accounts', Users, 'navAccounts'],
  ['settings', SlidersHorizontal, 'navSettings'],
  ['system', Settings2, 'navSystem'],
] as const;

export type Page = (typeof navItems)[number][0];
