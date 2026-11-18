import { App as AntApp, Badge, ConfigProvider, Drawer } from 'antd';
import { Select } from './components/Select';
import { Input } from './components/Input';
import { Button } from './components/Button';
import { AppRoot } from '@telegram-apps/telegram-ui';
import { SheetModal as Modal } from './components/SheetModal';
import ruRU from 'antd/locale/ru_RU';
import 'dayjs/locale/ru';
import { Building2, History, Plus, Settings } from 'lucide-react';
import { useLayoutEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { TableImportModal } from './components/TableImportModal';
import { VoiceReportDrawer } from './components/VoiceReportDrawer';
import { LaunchScreen } from './components/LaunchScreen';

import { LiveSearch } from './components/LiveSearch';
import { TelegramIcon } from './components/TelegramIcon';
import './final-polish.css';
import './connection-card.css';
import { useWorkspace } from './hooks/useWorkspace';
import './import-details.css';
import './mobile.css';
import { ChangesPage } from './pages/ChangesPage';
import { DailyReportPage } from './pages/DailyReportPage';
import { ObjectsPage } from './pages/ObjectsPage';
import { ObjectPage } from './pages/ObjectPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { useTableNotifications } from './pages/TableNotifications';
import { TeamPage } from './pages/TeamPage';
import { RemindersPage } from './pages/RemindersPage';
import './reports.css';
import './search-controls.css';
import './telegram.css';
import './mobile-refinements.css';
import './bottom-sheets.css';
import './avatar.css';
import './keyboard.css';
import './select-controls.css';
import './telegram-ios.css';
import './compact-workspace.css';
import './compact-lists.css';
import './desktop.css';
import './bottom-nav.css';
import './telegram-kit-tokens.css';
import './telegram-kit-components.css';
import { telegramTheme } from './lib/telegram-theme';
import { useInputVisibility } from './hooks/useInputVisibility';
import { useStartupScreen } from './hooks/useStartupScreen';
import { useAppRelease } from './hooks/useAppRelease';
import { useTelegramNotifications } from './hooks/useTelegramNotifications';
import type { HistoryRow, Project, Session } from './types';
export type WorkspaceView = ReturnType<typeof useWorkspace> & {
	session: Session;
	projects: Project[];
	todayRow: HistoryRow | undefined;
};
export function WorkspaceApp() {
	useInputVisibility();
	const controller = useWorkspace();
	const {
		session,
		data,
		failure,
		page,
		setPage,
		project,
		busy,
		lines,
		workPicker,
		setWorkPicker,
		replaceIndex,
		setReplaceIndex,
		projectOpen,
		setProjectOpen,
		objectForm,
		setObjectForm,
		projectName,
		setProjectName,
		projectOwner,
		setProjectOwner,
		users,
		userForm,
		setUserForm,
		editingUser,
		userId,
		setUserId,
		userName,
		setUserName,
		userRole,
		setUserRole,
		ownerFilter,
		active,
		positions,
		isAdmin,
		selectObject,
		addLine,
		loadUsers,
		openSettings,
		createObject,
		grant,
	} = controller;
	const content = useRef<HTMLElement>(null);
	const section = page === 'object' || page === 'today' ? controller.objectSection : null;
	useLayoutEffect(() => {
		if (!content.current || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
		const transition = content.current.animate([{ opacity: 0.75 }, { opacity: 1 }], {
			duration: 180,
			easing: 'ease-out',
		});
		return () => transition.cancel();
	}, [page, section]);
	useStartupScreen(Boolean(failure || (session && (!session.projects.length || data))));
	const notifications = useTelegramNotifications(session?.user.telegram_id);
	const tableInbox = useTableNotifications(session?.user.telegram_id, session?.user.role);
	useAppRelease(
		!session ||
			busy ||
			controller.switchingRole ||
			controller.page === 'more' ||
			Boolean(
				(controller.report && controller.dirty) ||
				controller.freeText.trim() ||
				controller.preview ||
				controller.textOpen ||
				workPicker ||
				objectForm ||
				projectOpen ||
				userForm ||
				controller.parsing ||
				controller.audioInput.recording ||
				controller.audioInput.pending,
			),
		{ page, project, day: controller.day, objectSection: controller.objectSection },
	);
	if (!session) return <LaunchScreen failure={failure} />;
	const projects = session.projects.filter(
		(p) =>
			(ownerFilter === 'all' || p.owner_id === ownerFilter) &&
			(controller.summaryProject === 'all' || p.id === controller.summaryProject),
	);
	const todayRow = data?.history.find((h) => h.date === session.today);
	const workspace = { ...controller, session, projects, todayRow };
	return (
		<div className="application">
			<div className="workspace">
				{isAdmin && page === 'today' && (
					<div className="context-bar">
						<button className="object-switch" onClick={() => setProjectOpen(true)}>
							<Building2 size={17} />
							<span>{active?.name || 'Выберите объект'}</span>
							<TelegramIcon name="chevron-down" size={15} />
						</button>
						<span className="role-label">{isAdmin ? 'Администратор' : 'Мастер'}</span>
					</div>
				)}
				<main className="content" ref={content}>
					{page === 'objects' && <ObjectsPage workspace={workspace} />}
					{(page === 'today' || page === 'object') &&
						(isAdmin ? (
							<DailyReportPage workspace={workspace} />
						) : (
							<ObjectPage key={project} workspace={workspace} />
						))}
					{page === 'history' && <ReportsPage workspace={workspace} />}
					{page === 'changes' && <ChangesPage workspace={workspace} />}
					{page === 'more' && (
						<SettingsPage
							workspace={workspace}
							notifications={notifications}
							tableInbox={tableInbox}
						/>
					)}
					{page === 'team' && <TeamPage workspace={workspace} />}
					{page === 'reminders' && <RemindersPage workspace={workspace} />}
				</main>
			</div>
			<nav className="bottom-nav" aria-label="Разделы приложения">
				{[
					{ id: 'objects', label: 'Объекты', icon: <TelegramIcon name="folder" size={22} /> },
					...(!isAdmin
						? [{ id: 'today', label: 'Отчёт', icon: <TelegramIcon name="report" size={22} /> }]
						: []),
					{ id: 'history', label: 'История', icon: <History size={22} /> },
					{ id: 'more', label: 'Настройки', icon: <Settings size={22} /> },
				].map((n) => {
					const selected =
						page === n.id ||
						(n.id === 'today' && page === 'object') ||
						(n.id === 'more' && ['team', 'reminders'].includes(page)) ||
						(n.id === 'history' && page === 'changes');
					return (
						<button
							key={n.id}
							type="button"
							aria-current={selected ? 'page' : undefined}
							className={selected ? 'active' : ''}
							onClick={() => {
								if (n.id === 'more') openSettings();
								else if (n.id === 'today' && !isAdmin && active)
									controller.openObjectSection('reports');
								else setPage(n.id);
							}}
						>
							<span className="bottom-nav-icon" aria-hidden>
								{n.id === 'more' ? (
									<Badge count={tableInbox.count} size="small" offset={[3, 0]}>
										{n.icon}
									</Badge>
								) : (
									n.icon
								)}
							</span>
							<span className="bottom-nav-label">{n.label}</span>
						</button>
					);
				})}
			</nav>
			<Drawer
				getContainer={() => document.getElementById('miniapp-surface') ?? document.body}
				placement="bottom"
				height="88dvh"
				title={replaceIndex !== null ? 'Выберите работу' : 'Добавить работу'}
				open={workPicker}
				onClose={() => {
					setWorkPicker(false);
					setReplaceIndex(null);
				}}
				className="mobile-drawer"
				destroyOnClose
			>
				<LiveSearch
					project={project}
					positions={positions}
					selected={
						replaceIndex === null ? lines.flatMap((l) => (l.item_id ? [l.item_id] : [])) : []
					}
					onSelect={addLine}
					onProjectMatch={(id) => {
						setWorkPicker(false);
						setReplaceIndex(null);
						selectObject(id);
					}}
				/>
			</Drawer>
			<VoiceReportDrawer workspace={workspace} />
			<Drawer
				getContainer={() => document.getElementById('miniapp-surface') ?? document.body}
				placement="bottom"
				height="70dvh"
				title="Объекты"
				open={projectOpen}
				onClose={() => setProjectOpen(false)}
				className="mobile-drawer"
			>
				<div className="switch-list">
					{session.projects.map((p) => (
						<button key={p.id} onClick={() => selectObject(p.id)}>
							<Building2 size={20} />
							<span>
								<b>{p.name}</b>
								<small>{p.owner_name}</small>
							</span>
							{p.id === project ? (
								<TelegramIcon name="check" size={20} />
							) : (
								<TelegramIcon name="chevron-right" size={18} />
							)}
						</button>
					))}
				</div>
				<Button
					block
					icon={<Plus size={17} />}
					onClick={() => {
						setProjectOpen(false);
						setObjectForm(true);
						if (isAdmin) void loadUsers();
					}}
				>
					Добавить объект
				</Button>
			</Drawer>
			<Modal
				title="Новый объект"
				open={objectForm}
				onCancel={() => setObjectForm(false)}
				okText="Добавить объект"
				cancelText="Отмена"
				confirmLoading={busy}
				onOk={createObject}
				okButtonProps={{ disabled: !projectName.trim() }}
			>
				<div className="form-fields">
					<label htmlFor="project-name">Название объекта</label>
					<Input
						id="project-name"
						value={projectName}
						onChange={(e) => setProjectName(e.target.value)}
						placeholder="Например: Детский сад, корпус 2"
					/>
					{isAdmin && (
						<>
							<label>Ответственный мастер</label>
							<Select
								value={projectOwner || session.user.telegram_id}
								onChange={setProjectOwner}
								options={users
									.filter((u) => u.enabled)
									.map((u) => ({ value: u.telegram_id, label: u.name }))}
							/>
						</>
					)}
				</div>
			</Modal>
			<Modal
				title={editingUser ? 'Настройки пользователя' : 'Добавить пользователя'}
				className="member-form-sheet"
				open={userForm}
				onCancel={() => setUserForm(false)}
				okText="Сохранить"
				cancelText="Отмена"
				confirmLoading={busy}
				cancelButtonProps={{ type: 'text' }}
				onOk={grant}
				okButtonProps={{ disabled: !userName.trim() || !/^\d+$/.test(userId) }}
			>
				<div className="form-fields member-form-fields">
					<label htmlFor="member-telegram-id">Telegram ID</label>
					<Input
						id="member-telegram-id"
						inputMode="numeric"
						value={userId}
						readOnly={!!editingUser}
						onChange={(e) => setUserId(e.target.value.replace(/\D/g, ''))}
						placeholder="Числовой ID пользователя"
					/>
					<label htmlFor="member-name">Имя</label>
					<Input
						id="member-name"
						value={userName}
						maxLength={100}
						onChange={(e) => setUserName(e.target.value)}
					/>
					<label htmlFor="member-role">Роль</label>
					<Select
						id="member-role"
						value={userRole}
						onChange={setUserRole}
						options={[
							{ value: 'master', label: 'Мастер' },
							{ value: 'admin', label: 'Администратор' },
						]}
					/>
					<small>
						{userRole === 'admin'
							? 'Просмотр всех объектов и управление доступом'
							: 'Работа только с назначенными объектами'}
					</small>
				</div>
			</Modal>
			{!isAdmin && <TableImportModal workspace={workspace} />}
		</div>
	);
}
export function renderApp() {
	createRoot(document.getElementById('root')!).render(<ThemedWorkspace />);
}

function ThemedWorkspace() {
	return (
		<ConfigProvider
			locale={ruRU}
			theme={telegramTheme()}
			modal={{
				closeIcon: <TelegramIcon name="close" size={20} />,
				closable: { 'aria-label': 'Закрыть' },
			}}
			drawer={{
				closeIcon: <TelegramIcon name="close" size={20} />,
				closable: { placement: 'end', 'aria-label': 'Закрыть' },
			}}
		>
			<AppRoot
				id="miniapp-surface"
				appearance="light"
				platform={document.documentElement.dataset.platform === 'apple' ? 'ios' : 'base'}
			>
				<AntApp message={{ maxCount: 2 }}>
					<WorkspaceApp />
				</AntApp>
			</AppRoot>
		</ConfigProvider>
	);
}
