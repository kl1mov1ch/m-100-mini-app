import { App, Button, Empty, Input, Modal } from 'antd';
import { KeyRound, Pencil, Plus, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import type { WorkspaceView } from '../App';
import type { DiskWebhook } from '../types';
import { FieldHelp } from './FieldHelp';

export function ProfileWebhooks({ workspace }: { workspace: WorkspaceView }) {
	const [editing, setEditing] = useState<DiskWebhook | null>(null);
	const [open, setOpen] = useState(false);
	const [name, setName] = useState('');
	const [url, setUrl] = useState('');
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState('');
	const { message, modal } = App.useApp();
	const edit = (item: DiskWebhook | null) => {
		setEditing(item);
		setName(item?.name || '');
		setUrl('');
		setError('');
		setOpen(true);
	};
	const save = async (event?: FormEvent<HTMLFormElement>) => {
		event?.preventDefault();
		if ((!editing && !url.trim()) || saving) return;
		setSaving(true);
		setError('');
		try {
			if (editing) await workspace.updateDiskWebhook(editing.id, { name, url });
			else await workspace.saveDiskWebhook({ name, url });
			setOpen(false);
			message.success(editing ? 'Вебхук обновлён' : 'Вебхук сохранён');
		} catch (failure) {
			setError((failure as Error).message);
		} finally {
			setSaving(false);
		}
	};
	const remove = (item: DiskWebhook) =>
		modal.confirm({
			className: 'action-confirm-sheet',
			title: 'Удалить сохранённый вебхук?',
			icon: null,
			content: (
				<div className="action-confirm-content">
					<strong>{item.name}</strong>
					<p>
						Он исчезнет из списка профиля. Подключённые объекты продолжат работать с сохранённым
						подключением. Это не отзывает ключ в Битрикс24.
					</p>
				</div>
			),
			okText: 'Удалить',
			cancelText: 'Отмена',
			okButtonProps: { danger: true },
			onOk: async () => {
				try {
					await workspace.deleteDiskWebhook(item.id);
					message.success('Вебхук удалён из профиля');
				} catch (failure) {
					message.error((failure as Error).message);
					throw failure;
				}
			},
		});
	return (
		<section className="settings-card profile-webhooks">
			<div className="settings-section-heading">
				<h2>
					<KeyRound size={18} /> Вебхуки Битрикс24 <FieldHelp topic="bitrix" />
				</h2>
				<Button
					type="text"
					aria-label="Добавить вебхук"
					icon={<Plus size={20} />}
					onClick={() => edit(null)}
				/>
			</div>
			{!workspace.diskWebhooks.length && (
				<Empty
					image={Empty.PRESENTED_IMAGE_SIMPLE}
					description="Сохраните вебхук для подключения таблиц"
				/>
			)}
			<ul>
				{workspace.diskWebhooks.map((item) => (
					<li key={item.id}>
						<div className="webhook-description">
							<strong>{item.name}</strong>
							<small>{item.portal}</small>
						</div>
						<Button
							type="text"
							aria-label={'Изменить вебхук ' + item.name}
							icon={<Pencil size={17} />}
							onClick={() => edit(item)}
						/>
						<Button
							type="text"
							danger
							aria-label={'Удалить вебхук ' + item.name}
							icon={<Trash2 size={17} />}
							onClick={() => remove(item)}
						/>
					</li>
				))}
			</ul>
			<Modal
				title={editing ? 'Изменить вебхук' : 'Новый вебхук'}
				open={open}
				onCancel={() => !saving && setOpen(false)}
				onOk={() => save()}
				confirmLoading={saving}
				okText="Сохранить"
				cancelText="Отмена"
				okButtonProps={{ disabled: !editing && !url.trim() }}
				cancelButtonProps={{ disabled: saving }}
				maskClosable={!saving}
				closable={!saving}
			>
				<form className="object-connection-form" onSubmit={save}>
					<label>
						Название
						<Input
							value={name}
							maxLength={80}
							placeholder="Рабочий портал"
							onChange={(event) => setName(event.target.value)}
							disabled={saving}
						/>
					</label>
					<label>
						Вебхук с правом «Диск»
						<Input.Password
							value={url}
							maxLength={500}
							placeholder={
								editing
									? 'Оставьте пустым, чтобы сохранить ключ'
									: 'https://ваш-портал.bitrix24.by/rest/…'
							}
							autoComplete="new-password"
							onChange={(event) => setUrl(event.target.value)}
							disabled={saving}
						/>
					</label>
					{editing && (
						<small>
							Новый ключ применяется при следующем выборе вебхука в подключении объекта.
						</small>
					)}
					{error && (
						<p className="form-error" role="alert">
							{error}
						</p>
					)}
				</form>
			</Modal>
		</section>
	);
}
