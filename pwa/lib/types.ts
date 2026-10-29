export type User={id:string;name:string;email:string;role:'user'|'moderator'};
export type Submission={id:string;owner_id:string;label:string;language:string;filename:string;size:number;mime:string;rights:number;training:number;research:number;moderation_status:string;processing_status:string;source_status:string;reason:string;revision:number;created_at:number;can_delete_source?:boolean;history?:{action:string;detail:string;created_at:number}[]};
export type Gesture={id:string;label:string;language:string;metadata:Record<string,unknown>};
export type Motion={id:string;label:string;sequence:number[][];fps:number;version:string;metadata:Record<string,unknown>};
