import { Button, Input, InputNumber, Tag, Upload, Select } from 'antd';
import { ObjectTableCard } from '../components/ObjectTableCard';
import { openExternalLink } from '../lib/telegram';
import { ProfileCard } from '../components/ProfileCard';
import { FieldHelp } from '../components/FieldHelp';
import 'dayjs/locale/ru';
import {
	ArrowRight,
	ChevronRight,
	FileSpreadsheet,
	RefreshCw,
	ShieldCheck,
	Sparkles,
	UploadCloud,
	Users,
} from 'lucide-react';

import type { WorkspaceView } from '../App';
export function SettingsPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		session,
		data,
		setPage,
		busy,
		url,
		setUrl,
		webhook,
		setWebhook,
		fileId,
		setFileId,
		aiKey,
		setAiKey,
		aiModel,
		setAiModel,
		active,
		positions,
		isAdmin,
		loadUsers,
		connect,
		importRemote,
		upload,
		connectAI,
		project,
		switchSettingsProject,
	} = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">{session.user.name}</span>
					<h1>Настройки</h1>
				</div>
				<span className="profile-badge">
					{isAdmin ? <ShieldCheck size={20} /> : <Users size={20} />}
				</span>
			</div>
			{isAdmin && (
				<button
					className="settings-menu"
					onClick={() => {
						void loadUsers();
						setPage('team');
					}}
				>
					<span className="settings-icon">
						<Users size={21} />
					</span>
					<span>
						<b>Команда и доступ</b>
						<small>Мастера, Telegram ID и роли</small>
					</span>
					<ChevronRight size={18} />
				</button>
			)}
			<ProfileCard workspace={workspace} />
			{isAdmin && (
				<button className="settings-menu" onClick={() => setPage('reminders')}>
					<span className="settings-icon">
						<Users size={21} />
					</span>
					<span>
						<b>Напоминания мастерам</b>
						<small>Сообщения в Telegram и расписание</small>
					</span>
					<ChevronRight size={18} />
				</button>
			)}
			{active && !isAdmin && (
				<>
					<>
						<section className="settings-card">
							<h2>
								<FileSpreadsheet size={20} />
								Таблица объекта
							</h2>
							<label htmlFor="table-project">Привязать таблицу к объекту</label>
							<Select
								id="table-project"
								className="object-table-select"
								value={project}
								onChange={switchSettingsProject}
								options={session.projects.map((object) => ({
									value: object.id,
									label: object.name,
								}))}
							/>
							<p className="settings-current">
								{data?.config.source_name || active.name} · {positions.length} работ
							</p>
							<Upload accept=".xlsx,.csv" showUploadList={false} beforeUpload={upload}>
								<Button block icon={<UploadCloud size={18} />} loading={busy}>
									Загрузить свою таблицу
								</Button>
							</Upload>
							<label>Ссылка Битрикс24</label>
							<Input
								value={url}
								onChange={(e) => setUrl(e.target.value)}
								placeholder="https://bitrix24public.com/…"
							/>
							<label>ID файла на Диске</label>
							<InputNumber
								min={1}
								value={fileId || null}
								onChange={setFileId}
								placeholder="Определяется по ссылке"
							/>
							<label>
								Вебхук с доступом к Диску <FieldHelp topic="bitrix" />
							</label>
							<Input.Password
								value={webhook}
								onChange={(e) => setWebhook(e.target.value)}
								placeholder={
									data?.config.has_webhook
										? 'Подключён · новый ключ для замены'
										: 'https://ваш-портал.bitrix24.by/rest/…'
								}
								autoComplete="off"
							/>
							<div className="stack-actions">
								<Button
									type="primary"
									onClick={importRemote}
									loading={busy}
									icon={<RefreshCw size={16} />}
								>
									{data?.config.source === 'bitrix'
										? 'Обновить связанную таблицу'
										: 'Связать таблицу с объектом'}
								</Button>
								<Button onClick={connect} loading={busy}>
									Сохранить доступ к таблице
								</Button>
								{url && (
									<Button
										type="link"
										href={url}
										onClick={(event) => openExternalLink(event, url)}
										target="_blank"
										rel="noreferrer"
									>
										Открыть оригинал
										<ArrowRight size={15} />
									</Button>
								)}
							</div>
						</section>
						<ObjectTableCard workspace={workspace} />
					</>
				</>
			)}
			{isAdmin && (
				<section className="settings-card">
					<h2>
						<Sparkles size={20} />
						Умный подбор
					</h2>
					<div className="ai-settings-state">
						<span>DeepSeek · экономный режим</span>
						<Tag color={session.ai_connected ? 'blue' : 'default'}>
							{session.ai_connected ? 'Подключён' : 'Нужен ключ'}
						</Tag>
					</div>
					<label>Модель</label>
					<Input value={aiModel} onChange={(e) => setAiModel(e.target.value)} />
					<label>
						Ключ API <FieldHelp topic="ai" />
					</label>
					<Input.Password
						value={aiKey}
						onChange={(e) => setAiKey(e.target.value)}
						placeholder={session.ai_connected ? 'Настроен · введите для замены' : 'Ключ DeepSeek'}
						autoComplete="off"
					/>
					<Button type="primary" block disabled={!aiKey.trim()} loading={busy} onClick={connectAI}>
						Подключить
					</Button>
				</section>
			)}
			<section className="account-card">
				<span className="profile-button">{session.user.name[0]}</span>
				<div>
					<b>{session.user.name}</b>
					<small>
						{isAdmin ? 'Администратор' : 'Мастер'}
						{session.user.telegram_id !== 'local-admin' ? ` · ID ${session.user.telegram_id}` : ''}
					</small>
				</div>
			</section>
		</>
	);
}
