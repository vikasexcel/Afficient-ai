import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";

interface Props {
  version: number;
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function RestoreVersionDialog({ version, open, onConfirm, onCancel }: Props) {
  return (
    <AlertDialog open={open}>
      <AlertDialogContent className="bg-[#0d0d14] border-white/[0.08] text-white">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-white">
            Restore Version {version}?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-white/50">
            The current workflow will be replaced with the snapshot from Version{" "}
            {version}. A new version is created so this action is fully reversible.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={onCancel}
            className="bg-transparent border-white/10 text-white/60 hover:text-white hover:bg-white/5"
          >
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-amber-600 hover:bg-amber-500 text-white border-0"
          >
            Restore
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
