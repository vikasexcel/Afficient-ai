import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

import { useState } from "react";

import { createCampaign } from "@/services/campaign";

export default function CreateCampaignDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");

  async function submit() {
    // Backend only accepts {name} today; the prompt template stays
    // local until the playbook integration lands.
    void prompt;
    await createCampaign({
      name,
    });

    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          New Campaign
        </Button>
      </DialogTrigger>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Create Campaign
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <Input
            placeholder="Campaign name"
            value={name}
            onChange={(e) =>
              setName(e.target.value)
            }
          />

          <Textarea
            rows={6}
            placeholder="Prompt Template"
            value={prompt}
            onChange={(e) =>
              setPrompt(e.target.value)
            }
          />

          <Button
            onClick={submit}
            className="w-full"
          >
            Create
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}