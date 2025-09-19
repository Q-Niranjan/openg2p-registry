from collections import defaultdict
from odoo import api, models

class MergePartnerAutomatic(models.TransientModel):
    _inherit = 'base.partner.merge.automatic.wizard'

    def _merge_g2p_reg_ids(self, src_partners, dst_partner):
        if 'g2p.reg.id' not in self.env:
            return

        G2PRegID = self.env['g2p.reg.id']
        all_reg_ids = G2PRegID.search([('partner_id', 'in', (src_partners + dst_partner).ids)])
        
        if not all_reg_ids:
            return

        grouped_records = defaultdict(list)
        for reg_id in all_reg_ids:
            key = (reg_id.id_type.id, (reg_id.value or '').strip().lower())
            grouped_records[key].append(reg_id)

        records_to_delete = G2PRegID.browse()
        records_to_update = []

        for records in grouped_records.values():
            if len(records) == 1:
                if records[0].partner_id != dst_partner:
                    records_to_update.append(records[0].id)
            else:
                best_record = self._select_best_reg_id(records, dst_partner)
                records_to_delete |= G2PRegID.browse([r.id for r in records if r.id != best_record.id])
                if best_record.partner_id != dst_partner:
                    records_to_update.append(best_record.id)

        if records_to_delete:
            records_to_delete.unlink()
        if records_to_update:
            G2PRegID.browse(records_to_update).write({'partner_id': dst_partner.id})


    def _select_best_reg_id(self, records, dst_partner):
        # TODO: Selection criteria is based on current assumptions
        #       (partner match > valid > expiry > create_date, tie-breaker on ID).
        #       Revisit if business rules change.
        best_record = None
        best_score = float("-inf")

        for r in records:
            score = 0
            if r.partner_id == dst_partner:
                score += 1000
            if r.status == "valid":
                score += 100
            if r.expiry_date:
                score += 10
            if r.create_date:
                score += r.create_date.timestamp() / 1000000
            score -= r.id / 100000

            if score > best_score:
                best_score = score
                best_record = r

        return best_record



    def _merge_group_memberships(self, src_partners, dst_partner):
        if 'g2p.group.membership' not in self.env:
            return

        G2PGroupMembership = self.env['g2p.group.membership']
        all_memberships = G2PGroupMembership.search([
            '|', ('group', 'in', (src_partners + dst_partner).ids),
            ('individual', 'in', (src_partners + dst_partner).ids)
        ])
        
        if not all_memberships:
            return

        final_memberships = {}
        to_delete = G2PGroupMembership.browse()
        to_update = {}
        
        for membership in all_memberships:
            group_id = dst_partner.id if membership.group in src_partners else membership.group.id
            individual_id = dst_partner.id if membership.individual in src_partners else membership.individual.id
            
            if group_id == individual_id:
                to_delete |= membership
                continue
            
            key = (group_id, individual_id)
            
            if key not in final_memberships:
                final_memberships[key] = membership
                if membership.group.id != group_id or membership.individual.id != individual_id:
                    to_update[membership.id] = {'group': group_id, 'individual': individual_id}
            else:
                existing = final_memberships[key]
                better = self._select_best_membership([existing, membership], dst_partner)
                
                if better == membership:
                    to_delete |= existing
                    final_memberships[key] = membership
                    to_update.pop(existing.id, None)
                    if membership.group.id != group_id or membership.individual.id != individual_id:
                        to_update[membership.id] = {'group': group_id, 'individual': individual_id}
                else:
                    to_delete |= membership

        for membership_id, values in to_update.items():
            membership = G2PGroupMembership.browse([membership_id])
            if membership.exists() and membership not in to_delete:
                membership.write(values)

        if to_delete:
            to_delete.unlink()


    def _select_best_membership(self, memberships, dst_partner):
        # TODO: Selection criteria is based on current assumptions:
        #       - Prefer memberships linked to dst_partner (group/individual).
        #       - Active > not ended > earlier start_date > more kinds.
        #       - Tie-breaker favors lower IDs.
        #       Revisit if business rules change.

        best_membership = None
        best_score = float("-inf")

        for m in memberships:
            score = 0
            if m.group == dst_partner or m.individual == dst_partner:
                score += 1000
            if m.status == "active":
                score += 100
            if not m.is_ended:
                score += 50
            if m.start_date:
                score += m.start_date.timestamp() / 1000000
            if m.kind:
                score += len(m.kind) * 5
            score -= m.id / 100000

            if score > best_score:
                best_score = score
                best_membership = m

        return best_membership



    def _merge_registrant_relationships(self, src_partners, dst_partner):
        if 'g2p.reg.rel' not in self.env:
            return

        G2PRegRel = self.env['g2p.reg.rel']
        all_relationships = G2PRegRel.search([
            '|', ('source', 'in', (src_partners + dst_partner).ids),
            ('destination', 'in', (src_partners + dst_partner).ids)
        ])
        
        if not all_relationships:
            return

        final_relationships = {}
        to_delete = G2PRegRel.browse()
        to_update = {}
        
        for rel in all_relationships:
            source_id = dst_partner.id if rel.source in src_partners else rel.source.id
            dest_id = dst_partner.id if rel.destination in src_partners else rel.destination.id
            
            if source_id == dest_id:
                to_delete |= rel
                continue
            
            key = (source_id, dest_id, rel.relation.id)
            
            if key not in final_relationships:
                final_relationships[key] = rel
                if rel.source.id != source_id or rel.destination.id != dest_id:
                    to_update[rel.id] = {'source': source_id, 'destination': dest_id}
            else:
                existing = final_relationships[key]
                better = self._select_best_relationship([existing, rel], dst_partner)
                
                if better == rel:
                    to_delete |= existing
                    final_relationships[key] = rel
                    to_update.pop(existing.id, None)
                    if rel.source.id != source_id or rel.destination.id != dest_id:
                        to_update[rel.id] = {'source': source_id, 'destination': dest_id}
                else:
                    to_delete |= rel

        for rel_id, values in to_update.items():
            relationship = G2PRegRel.browse([rel_id])
            if relationship.exists() and relationship not in to_delete:
                relationship.write(values)

        if to_delete:
            to_delete.unlink()

    def _select_best_relationship(self, relationships, dst_partner):
        # TODO: Selection criteria is based on current assumptions:
        #       - Prefer relationships involving dst_partner (source/destination).
        #       - Enabled > has start_date > no end_date.
        #       - Tie-breaker favors lower IDs.
        #       Revisit if business rules change.
        best_relationship = None
        best_score = float("-inf")

        for r in relationships:
            score = 0
            if r.source == dst_partner or r.destination == dst_partner:
                score += 1000
            if not r.disabled:
                score += 100
            if r.start_date:
                score += r.start_date.timestamp() / 1000000
            if not r.end_date:
                score += 50
            score -= r.id / 100000  

            if score > best_score:
                best_score = score
                best_relationship = r

        return best_relationship


    @api.model
    def _update_foreign_keys(self, src_partners, dst_partner):
        self._merge_g2p_reg_ids(src_partners, dst_partner)
        self._merge_group_memberships(src_partners, dst_partner)
        self._merge_registrant_relationships(src_partners, dst_partner)
        
        original_get_fk_on = type(self)._get_fk_on
        def filtered_get_fk_on(this, table):
            relations = original_get_fk_on(this, table)
            return [rel for rel in relations if rel[0] not in ('g2p_reg_id', 'g2p_group_membership', 'g2p_reg_rel')]

        cls = type(self)
        setattr(cls, "_get_fk_on", filtered_get_fk_on)
        try:
            super()._update_foreign_keys(src_partners, dst_partner)
        finally:
            setattr(cls, "_get_fk_on", original_get_fk_on)
