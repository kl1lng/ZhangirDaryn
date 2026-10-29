export function staleOfflineIds(saved:{id:string;version:string}[],catalog:{id:string;version:string}[]):string[]{
 if(!Array.isArray(catalog)||catalog.some(row=>typeof row.id!=='string'||typeof row.version!=='string'))throw new Error('Некорректная версия словаря.');
 const versions=new Map(catalog.map(row=>[row.id,row.version]));
 return saved.filter(row=>versions.get(row.id)!==row.version).map(row=>row.id);
}
