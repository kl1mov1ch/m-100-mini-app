import { App, Button, Input, Segmented } from 'antd';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { TelegramAvatar } from './TelegramAvatar';

export function ProfileCard({ workspace }: { workspace: WorkspaceView }) {
	const { session } = workspace;
	const { message, modal } = App.useApp();
	const [name, setName] = useState(session.user.name);
	const [busy, setBusy] = useState(false);
	const switchMode = (value: string) => {
		const apply = () => {
			localStorage.setItem('view-mode', value);
			location.reload();
		};
		if ((workspace.report && workspace.dirty) || name !== session.user.name) {
			modal.confirm({
				title: 'Есть несохранённые изменения',
				content:
					'Переключение режима закроет текущий черновик. Сначала сохраните изменения или продолжите без сохранения.',
				okText: 'Переключить',
				cancelText: 'Вернуться',
				onOk: apply,
			});
		} else apply();
	};
	const save = async () => {
		setBusy(true);
		try {
			await request('/profile', { name });
			await workspace.refresh(true);
			message.success('Имя сохранено');
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	return (
		<section className="settings-card profile-settings">
			<div className="profile-intro">
				<TelegramAvatar
					userId={session.user.telegram_id}
					name={session.user.name}
					source={session.user.avatar_url}
					size={52}
				/>
				<div>
					<b>{session.user.name}</b>
					<small>{session.user.username ? '@' + session.user.username : 'Профиль Telegram'}</small>
				</div>
			</div>
			<label htmlFor="profile-name">Ваше имя в приложении</label>
			<Input
				id="profile-name"
				value={name}
				onChange={(event) => setName(event.target.value)}
				maxLength={100}
			/>
			<Button
				block
				onClick={save}
				loading={busy}
				disabled={!name.trim() || name === session.user.name}
			>
				Сохранить имя
			</Button>
			{session.can_switch_role && (
				<>
					<label>Режим просмотра</label>
					<Segmented
						block
						value={session.view_mode}
						options={[
							{ value: 'admin', label: 'Администратор' },
							{ value: 'master', label: 'Мастер' },
						]}
						onChange={switchMode}
					/>
					<small className="profile-mode-help">
						В режиме мастера доступны только ваши объекты. Доступ к роли администратора сохраняется.
					</small>
				</>
			)}
		</section>
	);
}
