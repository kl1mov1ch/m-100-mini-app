import { Avatar, Button, Tag } from 'antd';
import 'dayjs/locale/ru';
import { ArrowLeft, Plus, Settings2 } from 'lucide-react';

import type { WorkspaceView } from '../App';
export function TeamPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		setPage,
		users,
		setUserForm,
		setUserId,
		setUserName,
		setUserRole,
		setUserEnabled,
		projects,
	} = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<button className="back-link" onClick={() => setPage('more')}>
						<ArrowLeft size={15} />
						Настройки
					</button>
					<h1>Команда</h1>
				</div>
				<Button
					type="primary"
					icon={<Plus size={17} />}
					onClick={() => {
						setUserId('');
						setUserName('');
						setUserRole('master');
						setUserEnabled(true);
						setUserForm(true);
					}}
				>
					Добавить
				</Button>
			</div>
			<div className="team-list">
				{users.map((u) => (
					<section className="team-card" key={u.telegram_id}>
						<Avatar size={42} src={u.avatar_url}>
							{u.name[0]}
						</Avatar>
						<div>
							<b>{u.name}</b>
							<small>
								{u.telegram_id === 'local-admin' ? 'Администратор' : `Telegram ID ${u.telegram_id}`}
							</small>
							<div>
								<Tag color={u.enabled ? 'blue' : 'default'}>
									{u.enabled
										? u.role === 'admin'
											? 'Администратор'
											: 'Мастер'
										: 'Доступ отключён'}
								</Tag>
								<small>{u.projects || 0} объектов</small>
							</div>
						</div>
						{u.telegram_id !== 'local-admin' && (
							<Button
								type="text"
								aria-label={'Изменить доступ ' + u.name}
								icon={<Settings2 size={18} />}
								onClick={() => {
									setUserId(u.telegram_id);
									setUserName(u.name);
									setUserRole(u.role);
									setUserEnabled(!!u.enabled);
									setUserForm(true);
								}}
							/>
						)}
					</section>
				))}
			</div>
		</>
	);
}
