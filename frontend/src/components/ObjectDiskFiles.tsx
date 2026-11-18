import { App } from 'antd';
import { Select } from './Select';
import { Input } from './Input';
import { Button } from './Button';
import { SheetModal as Modal } from './SheetModal';
import { ExternalLink, FilePlus2, FileSpreadsheet } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { openExternalLink } from '../lib/telegram';
import type { DiskFile } from '../types';

export function ObjectDiskFiles({ workspace }: { workspace: WorkspaceView }) {
	const { message } = App.useApp();
	const { project, active, data, diskWebhooks, importDiskBook, setData, setPage } = workspace;
	const [mode, setMode] = useState<'book' | 'report'>();
	const [name, setName] = useState('');
	const [workType, setWorkType] = useState('Основные работы');
	const [webhook, setWebhook] = useState<string>();
	const [saving, setSaving] = useState(false);
	const [publishing, setPublishing] = useState(false);
	const config = data?.config;
	if (!config) return null;
	const connected = config.source === 'bitrix';
	const canWriteSheet = connected && config.has_webhook && config.file_id > 0;
	const book = config.bitrix_project_book;
	const report = config.bitrix_report_file;
	const load = (next: 'book' | 'report') => {
		setMode(next);
		setName(book?.folder_name || active?.name || '');
		setWorkType(book?.work_type || 'Основные работы');
		const selected = next === 'report' ? config.bitrix_report_webhook_id : book?.webhook_id;
		setWebhook(selected || (diskWebhooks.length === 1 ? diskWebhooks[0].id : undefined));
	};
	const save = async () => {
		setSaving(true);
		try {
			if (mode === 'book') {
				await request(
					'/bitrix/disk-book',
					{ name, work_type: workType, webhook_id: webhook },
					project,
				);
				await workspace.refresh(true);
				message.success('Рабочая книга проверена и подключена');
			} else {
				const target = await request<{ webhook_id: string | null }>(
					'/bitrix/report-files',
					{ webhook_id: webhook || null },
					project,
				);
				setData((current) =>
					current?.project?.id === project
						? {
								...current,
								config: {
									...current.config,
									bitrix_report_webhook_id: target.webhook_id || '',
									bitrix_report_file:
										target.webhook_id === config.bitrix_report_webhook_id ? report : null,
								},
							}
						: current,
				);
				message.success(
					target.webhook_id ? 'Отправка отчёта настроена' : 'Отправка отчёта отключена',
				);
			}
			setMode(undefined);
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setSaving(false);
		}
	};
	const fileLink = (file: DiskFile) =>
		file.url && (
			<Button
				type="text"
				href={file.url}
				onClick={(event) => openExternalLink(event, file.url)}
				icon={<ExternalLink size={16} />}
			>
				Открыть на Диске
			</Button>
		);
	const publish = async () => {
		setPublishing(true);
		try {
			const file = await request<DiskFile>('/bitrix/report-files/publish', {}, project);
			setData((current) =>
				current?.project?.id === project
					? {
							...current,
							config: { ...current.config, bitrix_report_file: file },
						}
					: current,
			);
			message.success('Сводный отчёт сохранён на Диске');
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setPublishing(false);
		}
	};
	if (connected && canWriteSheet) return null;
	return (
		<section className="disk-files">
			<h3>Рабочая книга на Диске</h3>
			{!connected &&
				(book ? (
					<div className="disk-file">
						<strong title={book.name}>{book.name}</strong>
						<small>
							Можно перенести текущую смету в новую книгу или импортировать заполненный ранее файл.
						</small>
						<div>
							{fileLink(book)}
							<Button type="primary" onClick={() => load('book')}>
								Создать из данных объекта
							</Button>
							<Button onClick={importDiskBook} loading={workspace.busy}>
								Импортировать прежнюю книгу
							</Button>
						</div>
					</div>
				) : (
					<Button type="text" icon={<FilePlus2 size={17} />} onClick={() => load('book')}>
						Создать рабочую книгу
					</Button>
				))}
			{report && (
				<div className="disk-file">
					<strong>{report.name}</strong>
					<div>{fileLink(report)}</div>
				</div>
			)}
			<Button type="text" icon={<FileSpreadsheet size={17} />} onClick={() => load('report')}>
				{config.bitrix_report_webhook_id ? 'Настройки книги отчётов' : 'Отчёты на Диск'}
			</Button>
			{config.bitrix_report_webhook_id && (
				<Button type="text" loading={publishing} onClick={() => void publish()}>
					{report ? 'Обновить сводный отчёт' : 'Сохранить все дни на Диск'}
				</Button>
			)}
			<Modal
				className="disk-files-dialog"
				open={!!mode}
				title={mode === 'book' ? 'Создать рабочую книгу' : 'Книга отчётов на Диске'}
				confirmLoading={saving}
				okText={mode === 'book' ? 'Создать' : 'Сохранить'}
				cancelText="Отмена"
				onCancel={() => !saving && setMode(undefined)}
				onOk={() => void save()}
				okButtonProps={{
					disabled: mode === 'book' && (!name.trim() || !workType.trim() || !webhook),
				}}
			>
				<div className="object-connection-form">
					{mode === 'book' ? (
						<>
							<label>
								Название папки проекта
								<Input
									aria-label="Название папки проекта"
									value={name}
									maxLength={120}
									onChange={(event) => setName(event.target.value)}
								/>
							</label>
							<label>
								Вид работ
								<Input
									value={workType}
									maxLength={100}
									onChange={(e) => setWorkType(e.target.value)}
								/>
							</label>
							<p>
								На Диске будет создан файл «Отчётность проекта.xlsx» в папке выбранного вида работ.
							</p>
						</>
					) : (
						<p>
							После подтверждения отчёта приложение обновляет одну книгу со всеми днями объекта.
							Очистите выбор, чтобы отключить отправку.
						</p>
					)}
					<label>
						Вебхук Диска
						<Select
							aria-label="Вебхук Диска"
							value={webhook}
							onChange={setWebhook}
							allowClear={mode === 'report'}
							placeholder="Выберите из профиля"
							options={diskWebhooks.map(({ id, name, portal }) => ({
								value: id,
								label: name === portal ? name : `${name} · ${portal}`,
							}))}
						/>
					</label>
					{!diskWebhooks.length && (
						<Button
							type="text"
							onClick={() => {
								setMode(undefined);
								setPage('more');
							}}
						>
							Вебхуки в профиле
						</Button>
					)}
				</div>
			</Modal>
		</section>
	);
}
