import {
	Alert,
	App as AntApp,
	Button,
	ConfigProvider,
	Drawer,
	Input,
	InputNumber,
	Modal,
	Select,
	Spin,
	Switch,
} from 'antd';
import ruRU from 'antd/locale/ru_RU';
import 'dayjs/locale/ru';
import {
	Building2,
	Check,
	ChevronDown,
	ChevronRight,
	History,
	MoreHorizontal,
	Plus,
	ShieldCheck,
} from 'lucide-react';
import { createRoot } from 'react-dom/client';
import { ProjectLogo } from './components/ProjectLogo';
import { TableImportModal } from './components/TableImportModal';
import { VoiceReportDrawer } from './components/VoiceReportDrawer';

import { LiveSearch } from './components/LiveSearch';
import './final-polish.css';
import './connection-card.css';
import { useWorkspace } from './hooks/useWorkspace';
import './import-details.css';
import './mobile.css';
import { ChangesPage } from './pages/ChangesPage';
import { DailyReportPage } from './pages/DailyReportPage';
import { ObjectsPage } from './pages/ObjectsPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { TeamPage } from './pages/TeamPage';
import './search-controls.css';
import './telegram.css';
import type { HistoryRow, Project, Session } from './types';
export type WorkspaceView = ReturnType<typeof useWorkspace> & {
	session: Session;
	projects: Project[];
	todayRow: HistoryRow | undefined;
};
export function WorkspaceApp() {
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
		projectUrl,
		setProjectUrl,
		projectFile,
		setProjectFile,
		sample,
		setSample,
		users,
		userForm,
		setUserForm,
		userId,
		setUserId,
		userName,
		setUserName,
		userRole,
		setUserRole,
		userEnabled,
		setUserEnabled,
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
	if (failure && !session)
		return (
			<div className="launch-state">
				<ShieldCheck size={38} />
				<h1>Журнал работ</h1>
				<Alert type="warning" message={failure} />
				<Button onClick={() => location.reload()}>Обновить</Button>
			</div>
		);
	if (!session)
		return (
			<div className="launch-state">
				<Spin />
				<span>Открываем объекты…</span>
			</div>
		);
	const projects = session.projects.filter(
		(p) =>
			(ownerFilter === 'all' || p.owner_id === ownerFilter) &&
			(controller.summaryProject === 'all' || p.id === controller.summaryProject),
	);
	const todayRow = data?.history.find((h) => h.date === session.today);
	const workspace = { ...controller, session, projects, todayRow };
	return (
		<div className="application">
			<header className="app-header">
				<button className="app-wordmark" onClick={() => setPage('objects')}>
					<span>
						<ProjectLogo />
					</span>
					<b>Журнал работ</b>
				</button>
				<div className="header-user">
					<span>{session.user.name}</span>
					<button className="profile-button" onClick={openSettings} aria-label="Профиль">
						{session.user.name[0]}
					</button>
				</div>
			</header>
			<div className="workspace">
				<div className="context-bar">
					<button className="object-switch" onClick={() => setProjectOpen(true)}>
						<Building2 size={17} />
						<span>{active?.name || 'Выберите объект'}</span>
						<ChevronDown size={15} />
					</button>
					<span className="role-label">{isAdmin ? 'Администратор' : 'Мастер'}</span>
				</div>
				<main className="content">
					{page === 'objects' && <ObjectsPage workspace={workspace} />}
					{page === 'today' && <DailyReportPage workspace={workspace} />}
					{page === 'history' && <ReportsPage workspace={workspace} />}
					{page === 'changes' && <ChangesPage workspace={workspace} />}
					{page === 'more' && <SettingsPage workspace={workspace} />}
					{page === 'team' && <TeamPage workspace={workspace} />}
				</main>
			</div>
			<nav className="bottom-nav">
				{[
					{ id: 'objects', label: 'Объекты', icon: Building2 },
					{ id: 'today', label: 'Отчёт', icon: Plus },
					{ id: 'history', label: 'История', icon: History },
					{ id: 'more', label: 'Ещё', icon: MoreHorizontal },
				].map((n) => (
					<button
						key={n.id}
						onClick={() => (n.id === 'more' ? openSettings() : setPage(n.id))}
						className={
							page === n.id ||
							(n.id === 'more' && page === 'team') ||
							(n.id === 'history' && page === 'changes')
								? 'active'
								: ''
						}
					>
						<n.icon size={22} />
						<span>{n.label}</span>
					</button>
				))}
			</nav>
			<Drawer
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
				/>
			</Drawer>
			<VoiceReportDrawer workspace={workspace} />
			<Drawer
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
							{p.id === project ? <Check size={20} /> : <ChevronRight size={18} />}
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
					<label>Название объекта</label>
					<Input
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
					<label>Ссылка на таблицу Битрикс24</label>
					<Input
						value={projectUrl}
						onChange={(e) => setProjectUrl(e.target.value)}
						placeholder="Можно подключить позже"
					/>
					<label>ID файла, если известен</label>
					<InputNumber value={projectFile} onChange={setProjectFile} min={1} />
					{session.mode === 'development' && (
						<div className="switch-row">
							<span>Начать с шаблона сметы</span>
							<Switch checked={sample} onChange={setSample} />
						</div>
					)}
				</div>
			</Modal>
			<Modal
				title="Доступ к приложению"
				open={userForm}
				onCancel={() => setUserForm(false)}
				okText="Сохранить"
				cancelText="Отмена"
				confirmLoading={busy}
				onOk={grant}
				okButtonProps={{ disabled: !userName.trim() || !/^\d+$/.test(userId) }}
			>
				<div className="form-fields">
					<label>Telegram ID</label>
					<Input
						inputMode="numeric"
						value={userId}
						onChange={(e) => setUserId(e.target.value.replace(/\D/g, ''))}
						placeholder="Числовой ID пользователя"
					/>
					<label>Имя</label>
					<Input value={userName} onChange={(e) => setUserName(e.target.value)} />
					<label>Роль</label>
					<Select
						value={userRole}
						onChange={setUserRole}
						options={[
							{ value: 'master', label: 'Мастер — только свои объекты' },
							{ value: 'admin', label: 'Администратор — все объекты' },
						]}
					/>
					<div className="switch-row">
						<span>Доступ разрешён</span>
						<Switch checked={userEnabled} onChange={setUserEnabled} />
					</div>
				</div>
			</Modal>
			<TableImportModal workspace={workspace} />
		</div>
	);
}
export function renderApp() {
	createRoot(document.getElementById('root')!).render(
		<ConfigProvider
			locale={ruRU}
			theme={{
				token: {
					colorPrimary: '#2563eb',
					colorInfo: '#2563eb',
					colorText: '#172b4d',
					colorTextSecondary: '#7a879d',
					colorBorder: '#dfe6f1',
					borderRadius: 12,
					fontFamily: 'Inter, "Segoe UI", Arial, sans-serif',
					controlHeight: 46,
				},
				components: {
					Button: { primaryShadow: 'none' },
					InputNumber: { controlWidth: 100 },
				},
			}}
		>
			<AntApp>
				<WorkspaceApp />
			</AntApp>
		</ConfigProvider>,
	);
}
