import { confirmSheet } from '../components/SheetModal';
import { App, Button, Tag } from 'antd';
import 'dayjs/locale/ru';
import { ChevronRight, Plus, Settings2, Trash2, TriangleAlert } from 'lucide-react';
import { useEffect, useEffectEvent } from 'react';

import type { WorkspaceView } from '../App';
import { CompactWorkEditor } from '../components/CompactRow';
import { countLabel } from '../lib/format';
import { TelegramAvatar } from '../components/TelegramAvatar';
import { request } from '../lib/api';
import type { User } from '../types';
import dayjs from '../lib/date';
import './team.css';

export function TeamPage({ workspace }: { workspace: WorkspaceView }) {
	const { modal, message } = App.useApp();
	const { users, openUserForm, loadUsers, selectObject, session } = workspace;
	const refresh = useEffectEvent(() => {
		if (document.visibilityState === 'visible') void loadUsers(true);
	});
	useEffect(() => {
		const timer = window.setInterval(refresh, 20000);
		document.addEventListener('visibilitychange', refresh);
		return () => {
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', refresh);
		};
	}, []);
	const remove = (user: User) =>
		confirmSheet(modal, {
			closable: true,
			title: 'Удалить пользователя?',
			icon: <TriangleAlert color="#a66b00" size={21} />,
			content: <p>{user.name} потеряет доступ к приложению. Объекты и отчёты сохранятся.</p>,
			okText: 'Удалить пользователя',
			cancelText: 'Отмена',
			okButtonProps: { danger: true },
			onOk: async () => {
				try {
					await request('/admin/users/' + encodeURIComponent(user.telegram_id) + '/delete', {});
					await loadUsers();
					message.success('Пользователь удалён из команды');
				} catch (failure) {
					message.error((failure as Error).message);
					throw failure;
				}
			},
		});
	return (
		<>
			<div className="page-title">
				<div>
					<h1>Команда</h1>
				</div>
				<Button type="primary" icon={<Plus size={17} />} onClick={() => openUserForm()}>
					Добавить
				</Button>
			</div>
			<div className="team-list compact-list">
				{users.map((u) => (
					<CompactWorkEditor
						key={u.telegram_id}
						title={u.name}
						description={
							u.open_project
								? 'Открыт · ' + u.open_project.name
								: u.enabled
									? u.online
										? 'В приложении'
										: 'Не в сети'
									: 'Доступ отключён'
						}
						value={countLabel(u.projects || 0, 'объект', 'объекта', 'объектов')}
						attention={!u.enabled}
						leading={
							<TelegramAvatar
								userId={u.telegram_id}
								name={u.name}
								source={u.avatar_url}
								size={30}
							/>
						}
					>
						{(close) => {
							const openProject = (id: string) => {
								close();
								selectObject(id);
							};
							return (
								<>
									<section className="team-card work-detail team-member">
										<TelegramAvatar
											userId={u.telegram_id}
											name={u.name}
											source={u.avatar_url}
											size={42}
										/>
										<div>
											<b>{u.name}</b>
											<small>
												{u.telegram_id === 'local-admin'
													? 'Администратор'
													: `Telegram ID ${u.telegram_id}`}
											</small>
											<div>
												<Tag color={u.enabled ? 'blue' : 'default'}>
													{u.enabled
														? u.role === 'admin'
															? 'Администратор'
															: 'Мастер'
														: 'Доступ отключён'}
												</Tag>
												<Tag color={u.online ? 'green' : 'default'}>
													{u.online ? 'В сети' : 'Не в сети'}
												</Tag>
											</div>
											{!u.online && !!u.last_seen && (
												<small>
											Последняя активность {dayjs(u.last_seen * 1000).format('DD.MM · HH:mm')}
												</small>
											)}
										</div>
										{u.telegram_id !== 'local-admin' && (
											<div className="team-actions">
												<Button
													type="text"
													aria-label={'Изменить доступ ' + u.name}
													icon={<Settings2 size={18} />}
													onClick={() => {
														close();
														openUserForm(u);
													}}
												>
													Изменить доступ
												</Button>
												{u.telegram_id !== session.user.telegram_id && (
													<Button
														type="text"
														danger
														aria-label={'Удалить пользователя ' + u.name}
														icon={<Trash2 size={18} />}
														onClick={() => remove(u)}
													/>
												)}
											</div>
										)}
									</section>
									<div className="team-projects">
										{u.open_project && (
											<>
												<h3>Сейчас открыт</h3>
												<button
													type="button"
													className="team-project-link"
													onClick={() => openProject(u.open_project!.id)}
												>
													<span>{u.open_project.name}</span>
													<ChevronRight size={16} aria-hidden />
												</button>
											</>
										)}
										<h3>Назначенные объекты</h3>
										{u.assigned_projects?.length ? (
											<ul className="team-project-list">
												{u.assigned_projects.map((project) => (
													<li key={project.id}>
														<button
															type="button"
															className="team-project-link"
															onClick={() => openProject(project.id)}
														>
															<span>{project.name}</span>
															<ChevronRight size={16} aria-hidden />
														</button>
													</li>
												))}
											</ul>
										) : (
											<p>Объекты не назначены</p>
										)}
									</div>
								</>
							);
						}}
					</CompactWorkEditor>
				))}
			</div>
		</>
	);
}
