import { Button, Tag } from 'antd';
import { RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { BitrixReviewModal } from './BitrixReviewModal';

export function BitrixReadStatus({ workspace }: { workspace: WorkspaceView }) {
	const { data, isAdmin, project, readingBitrix, refreshBitrix } = workspace;
	const [reviewProject, setReviewProject] = useState<string | null>(null);
	if (data?.config.source !== 'bitrix') return null;
	const read = data.config.bitrix_read;
	const updatedAt = read?.updated_at || data.config.last_import;
	return (
		<div className="bitrix-read-status">
			<div>
				{read?.status === 'unavailable' ? (
					<Tag color="gold">Битрикс24 недоступен · сохранённые данные</Tag>
				) : read?.status === 'review' ? (
					<Tag color="gold">Есть различия с Битрикс24</Tag>
				) : (
					<Tag color={read ? 'green' : 'default'}>Битрикс24</Tag>
				)}
				{updatedAt && <small>{dayjs(updatedAt).format('D MMM, HH:mm')}</small>}
				{read?.status === 'review' && !isAdmin && (
					<Button
						size="small"
						icon={<Sparkles size={15} />}
						onClick={() => setReviewProject(project)}
					>
						Разобрать различия
					</Button>
				)}
			</div>
			<Button
				type="text"
				size="small"
				title="Обновить данные Битрикс24"
				aria-label="Обновить данные Битрикс24"
				loading={readingBitrix}
				icon={<RefreshCw size={15} />}
				onClick={() => void refreshBitrix(true)}
			/>
			{reviewProject === project && !isAdmin && (
				<BitrixReviewModal workspace={workspace} close={() => setReviewProject(null)} />
			)}
		</div>
	);
}
